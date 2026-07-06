from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
VERSION = "v1.1.0"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def watchlist_count(path: Path) -> int:
    payload = load_json(path, {"watchlist": []})
    if isinstance(payload, dict):
        values = payload.get("watchlist", [])
        return len(values) if isinstance(values, list) else 0
    if isinstance(payload, list):
        return len(payload)
    return 0


def next_scan_time(now: datetime, interval_minutes: int) -> str:
    interval = max(interval_minutes, 1)
    minute = ((now.minute // interval) + 1) * interval
    next_time = now.replace(second=0, microsecond=0)
    if minute >= 60:
        next_time = next_time.replace(minute=0) + timedelta(hours=1)
    else:
        next_time = next_time.replace(minute=minute)
    return next_time.strftime("%Y-%m-%d %H:%M:%S")


def latest_time(items: list[dict[str, Any]], key: str) -> str:
    values = [str(item.get(key, "")) for item in items if item.get(key)]
    return max(values) if values else ""


def main() -> int:
    config = load_json(CONFIG_DIR / "config.json", {})
    timezone = ZoneInfo(config.get("timezone", "Asia/Shanghai"))
    now = datetime.now(timezone).replace(tzinfo=None)
    latest = load_json(DATA_DIR / "latest_signals.json", {"items": []})
    items = latest.get("items", []) if isinstance(latest, dict) else []
    error = os.getenv("SXT_STATUS_ERROR", "GitHub Actions monitor step failed.").strip()
    last_scan = now.strftime("%Y-%m-%d %H:%M:%S")
    next_scan = next_scan_time(now, int(config.get("scan_interval_minutes", 15)))

    write_json(
        DATA_DIR / "status.json",
        {
            "status": "error",
            "last_scan": last_scan,
            "last_scan_time": last_scan,
            "last_daily_time": latest_time(items, "last_daily_time"),
            "last_15m_time": latest_time(items, "last_15m_time"),
            "is_trading_time": bool(latest.get("is_trading_time", False)) if isinstance(latest, dict) else False,
            "force_scan": bool(latest.get("force_scan", False)) if isinstance(latest, dict) else False,
            "message": error[:300],
            "next_scan": next_scan,
            "next_scan_time": next_scan,
            "stocks": watchlist_count(CONFIG_DIR / "watchlist.json"),
            "signals": sum(1 for item in items if item.get("status") == "ALERT"),
            "duration_seconds": 0,
            "last_error": error[:300],
            "workflow": "failed",
            "data_source": str(config.get("data_source", "a-stock-data/tencent")),
            "version": VERSION,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
