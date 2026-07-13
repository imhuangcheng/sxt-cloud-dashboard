from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from calc_sxt import calculate_sxt
from chart import save_15m_chart
from fetch_data import fetch_15m, fetch_daily, fetch_stock_name, fetch_stock_names, normalize_stock
from notifier import (
    load_alert_history,
    notify_signal,
    prune_history,
    record_alert,
    save_alert_history,
    should_send_alert,
)
from watchlist_manager import all_symbols, load_groups, sync_legacy


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
LOGGER = logging.getLogger("sxt-cloud-monitor")
VERSION = "v1.1.0"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_bar_time(frame: Any) -> str:
    if frame is None or frame.empty:
        return ""
    return frame.iloc[-1]["datetime"].strftime("%Y-%m-%d %H:%M:%S")


def load_watchlist(path: Path) -> list[Any]:
    payload = load_json(path, {"watchlist": []})
    if isinstance(payload, dict):
        values = payload.get("watchlist", [])
        return values if isinstance(values, list) else []
    if isinstance(payload, list):
        return payload
    return []


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def is_trading_time(now: datetime, sessions: list[list[str]]) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.time()
    return any(parse_hhmm(start) <= current <= parse_hhmm(end) for start, end in sessions)


def next_scan_time(now: datetime, interval_minutes: int) -> str:
    interval = max(interval_minutes, 1)
    minute = ((now.minute // interval) + 1) * interval
    next_time = now.replace(second=0, microsecond=0)
    if minute >= 60:
        next_time = next_time.replace(minute=0) + timedelta(hours=1)
    else:
        next_time = next_time.replace(minute=minute)
    return next_time.strftime("%Y-%m-%d %H:%M:%S")


def build_status_payload(
    *,
    now: datetime,
    config: dict[str, Any],
    watchlist: list[Any],
    signals: int = 0,
    duration_seconds: float = 0,
    last_error: str = "",
    last_daily_time: str = "",
    last_15m_time: str = "",
    is_trading: bool = False,
    force_scan: bool = False,
    message: str = "",
    workflow: str = "success",
    data_updated_at: str = "",
) -> dict[str, Any]:
    last_scan = now.strftime("%Y-%m-%d %H:%M:%S")
    next_scan = next_scan_time(now, int(config.get("scan_interval_minutes", 15)))
    return {
        "status": "running" if workflow == "success" else "error",
        "last_scan": last_scan,
        "last_scan_time": last_scan,
        "data_updated_at": data_updated_at,
        "last_daily_time": last_daily_time,
        "last_15m_time": last_15m_time,
        "is_trading_time": is_trading,
        "force_scan": force_scan,
        "message": message,
        "next_scan": next_scan,
        "next_scan_time": next_scan,
        "stocks": len(watchlist),
        "signals": signals,
        "duration_seconds": round(duration_seconds, 2),
        "last_error": last_error,
        "workflow": workflow,
        "data_source": str(config.get("data_source", "a-stock-data/tencent")),
        "version": VERSION,
    }


def status_for(daily_sxt: int | None, minute15_sxt: int | None, target_daily: int, target_15m: int) -> str:
    if daily_sxt is None or minute15_sxt is None:
        return "NO_DATA"
    if daily_sxt == target_daily and minute15_sxt == target_15m:
        return "ALERT"
    return "WATCH"


def build_non_trading_payload(now: datetime, previous: dict[str, Any]) -> dict[str, Any]:
    return {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "data_updated_at": previous.get("data_updated_at", ""),
        "is_trading_time": False,
        "message": "Outside A-share trading sessions, scan skipped.",
        "items": previous.get("items", []),
    }


def latest_time(items: list[dict[str, Any]], key: str) -> str:
    values = [str(item.get(key, "")) for item in items if item.get(key)]
    return max(values) if values else ""


def main() -> int:
    started_at = datetime.now()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_json(CONFIG_DIR / "config.json", {})
    groups = load_groups(CONFIG_DIR / "watchlist_groups.json", CONFIG_DIR / "watchlist.json")
    watchlist = sync_legacy(groups, CONFIG_DIR / "watchlist.json")
    timezone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    now = datetime.now(timezone).replace(tzinfo=None)
    latest_path = DATA_DIR / "latest_signals.json"
    latest_alias_path = DATA_DIR / "latest.json"
    status_path = DATA_DIR / "status.json"
    history_path = DATA_DIR / "alert_history.json"
    previous_latest = load_json(latest_path, {"items": []})
    previous_status = load_json(status_path, {})
    force_scan = os.getenv("SXT_FORCE_SCAN", "").strip().lower() in {"1", "true", "yes"}
    trading_now = is_trading_time(now, config.get("trading_sessions", []))

    if not force_scan and not trading_now:
        LOGGER.info("outside trading sessions, skip scan because SXT_FORCE_SCAN is not enabled")
        previous_items = previous_latest.get("items", []) if isinstance(previous_latest, dict) else []
        non_trading_payload = build_non_trading_payload(now, previous_latest)
        write_json(latest_path, non_trading_payload)
        write_json(latest_alias_path, non_trading_payload)
        write_json(
            status_path,
            build_status_payload(
                now=now,
                config=config,
                watchlist=watchlist,
                signals=sum(1 for item in previous_items if item.get("status") == "ALERT"),
                duration_seconds=(datetime.now() - started_at).total_seconds(),
                last_daily_time=latest_time(previous_items, "last_daily_time"),
                last_15m_time=latest_time(previous_items, "last_15m_time"),
                data_updated_at=str(previous_status.get("data_updated_at", "") or previous_latest.get("data_updated_at", "")),
                is_trading=trading_now,
                force_scan=force_scan,
                message="Outside A-share trading sessions, scan skipped because force_scan is false.",
            ),
        )
        return 0
    if force_scan and not trading_now:
        LOGGER.info("SXT_FORCE_SCAN is enabled, fetching latest available data outside trading sessions")
    elif force_scan:
        LOGGER.info("SXT_FORCE_SCAN is enabled, running scan during trading sessions")

    alert_condition = config.get("alert_condition", {})
    target_daily = int(alert_condition.get("daily_sxt", 2))
    target_15m = int(alert_condition.get("minute15_sxt", 2))
    min_daily_bars = int(config.get("min_daily_bars", 80))
    min_minute15_bars = int(config.get("min_minute15_bars", 120))
    dedup_minutes = int(config.get("dedup_minutes", 240))
    data_source = str(config.get("data_source", "a-stock-data/tencent"))
    history = load_alert_history(history_path)
    prune_history(history, now)

    stocks = [normalize_stock(raw_stock) for raw_stock in all_symbols(groups)]
    try:
        stock_names = fetch_stock_names(stocks)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("batch stock name lookup failed: %s", exc)
        stock_names = {}

    items: list[dict[str, Any]] = []
    for stock in stocks:
        stock_name = stock_names.get(stock.code) or fetch_stock_name(stock)
        item: dict[str, Any] = {
            "code": stock.code,
            "name": stock_name,
            "market": stock.market,
            "daily_sxt": None,
            "minute15_sxt": None,
            "status": "NO_DATA",
            "last_daily_time": None,
            "last_15m_time": None,
            "error": "",
        }

        if not stock.supported:
            item["status"] = "UNSUPPORTED"
            item["error"] = stock.reason
            LOGGER.warning("skip unsupported stock %s: %s", stock.code, stock.reason)
            items.append(item)
            continue

        try:
            daily = fetch_daily(stock)
            minute15 = fetch_15m(stock)
            LOGGER.info(
                "stock=%s latest_daily_bar_time=%s latest_15m_bar_time=%s",
                stock.code,
                latest_bar_time(daily) or "-",
                latest_bar_time(minute15) or "-",
            )
            daily_result = calculate_sxt(daily, min_bars=min_daily_bars)
            minute15_result = calculate_sxt(minute15, min_bars=min_minute15_bars)
            item.update(
                {
                    "daily_sxt": daily_result.get("sxt_value"),
                    "minute15_sxt": minute15_result.get("sxt_value"),
                    "daily_signal": daily_result.get("signal_text"),
                    "minute15_signal": minute15_result.get("signal_text"),
                    "last_daily_time": daily_result.get("last_datetime"),
                    "last_15m_time": minute15_result.get("last_datetime"),
                }
            )
            item["status"] = status_for(item["daily_sxt"], item["minute15_sxt"], target_daily, target_15m)

            if (
                config.get("enable_serverchan", True)
                and item["status"] == "ALERT"
                and should_send_alert(history, stock.code, item["last_15m_time"], now, dedup_minutes)
            ):
                chart_path = None
                try:
                    chart_path = save_15m_chart(
                        minute15,
                        item,
                        Path(tempfile.gettempdir()) / f"sxt_{stock.code}_{str(item['last_15m_time']).replace(':', '').replace(' ', '_')}.png",
                    )
                except Exception as chart_exc:  # noqa: BLE001
                    LOGGER.exception("15m chart generation failed for %s", stock.code)
                    item["error"] = f"15分钟K截图生成失败: {chart_exc}"
                ok, error = notify_signal(
                    item,
                    data_source,
                    chart_path=chart_path,
                    enable_serverchan=bool(config.get("enable_serverchan", True)),
                    enable_wecom=bool(config.get("enable_wecom", True)),
                )
                record_alert(
                    history,
                    stock.code,
                    stock.display_name,
                    str(item["last_15m_time"]),
                    now,
                    "sent" if ok else "failed",
                    error,
                )
        except Exception as exc:  # noqa: BLE001
            item["status"] = "ERROR"
            item["error"] = str(exc)
            LOGGER.info(
                "stock=%s latest_daily_bar_time=%s latest_15m_bar_time=%s",
                stock.code,
                item.get("last_daily_time") or "-",
                item.get("last_15m_time") or "-",
            )
            LOGGER.exception("scan failed for %s", stock.code)

        items.append(item)

    payload = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "data_updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "is_trading_time": trading_now,
        "force_scan": force_scan,
        "message": "Force scan completed with latest available data." if force_scan and not trading_now else "Scan completed.",
        "items": items,
    }
    write_json(latest_path, payload)
    write_json(latest_alias_path, payload)
    save_alert_history(history_path, history)
    write_json(
        status_path,
        build_status_payload(
            now=now,
            config=config,
            watchlist=watchlist,
            signals=sum(1 for item in items if item.get("status") == "ALERT"),
            duration_seconds=(datetime.now() - started_at).total_seconds(),
            last_error="; ".join(item.get("error", "") for item in items if item.get("status") == "ERROR")[:300],
            last_daily_time=latest_time(items, "last_daily_time"),
            last_15m_time=latest_time(items, "last_15m_time"),
            data_updated_at=payload["data_updated_at"],
            is_trading=trading_now,
            force_scan=force_scan,
            message=payload["message"],
        ),
    )
    LOGGER.info("scan completed items=%s", len(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
