from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
try:
    import requests
except ImportError:  # pragma: no cover - fallback for very small local runtimes
    requests = None


LOGGER = logging.getLogger(__name__)
SERVERCHAN_URL = "https://sctapi.ftqq.com/{send_key}.send"


def load_alert_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("alert history is invalid, starting with empty history")
        return {"items": []}


def save_alert_history(path: Path, history: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def should_send_alert(
    history: dict[str, Any],
    code: str,
    minute15_time: str | None,
    now: datetime,
    dedup_minutes: int,
) -> bool:
    if not minute15_time:
        return False
    key = f"{code}|{minute15_time}"
    cutoff = now - timedelta(minutes=dedup_minutes)
    for item in history.get("items", []):
        if item.get("key") != key:
            continue
        if item.get("status") != "sent":
            continue
        sent_at = _parse_time(item.get("sent_at"))
        if sent_at is None or sent_at >= cutoff:
            return False
    return True


def record_alert(
    history: dict[str, Any],
    code: str,
    name: str,
    minute15_time: str,
    sent_at: datetime,
    status: str,
    error: str = "",
) -> None:
    history.setdefault("items", []).append(
        {
            "key": f"{code}|{minute15_time}",
            "code": code,
            "name": name,
            "minute15_time": minute15_time,
            "sent_at": sent_at.strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "error": error,
        }
    )


def prune_history(history: dict[str, Any], now: datetime, keep_days: int = 30) -> None:
    cutoff = now - timedelta(days=keep_days)
    kept = []
    for item in history.get("items", []):
        sent_at = _parse_time(item.get("sent_at"))
        if sent_at is None or sent_at >= cutoff:
            kept.append(item)
    history["items"] = kept


def send_serverchan(title: str, content: str, timeout: int = 12) -> tuple[bool, str]:
    send_key = os.getenv("SERVERCHAN_SEND_KEY", "").strip()
    if not send_key:
        LOGGER.warning("SERVERCHAN_SEND_KEY is not configured, skip notification")
        return False, "missing SERVERCHAN_SEND_KEY"

    if requests is not None:
        try:
            response = requests.post(
                SERVERCHAN_URL.format(send_key=send_key),
                data={"title": title, "desp": content},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("ServerChan push failed: %s", exc)
            return False, str(exc)
        if payload.get("code") not in {0, "0"}:
            message = str(payload)
            LOGGER.error("ServerChan returned error: %s", message)
            return False, message
        return True, ""

    body = urlencode({"title": title, "desp": content}).encode("utf-8")
    request = Request(
        SERVERCHAN_URL.format(send_key=send_key),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        LOGGER.error("ServerChan push failed: %s", exc)
        return False, str(exc)

    if payload.get("code") not in {0, "0"}:
        message = str(payload)
        LOGGER.error("ServerChan returned error: %s", message)
        return False, message
    return True, ""


def notify_signal(item: dict[str, Any], data_source: str) -> tuple[bool, str]:
    code = item.get("code", "")
    name = item.get("name") or "-"
    title = f"SXT双周期信号：{code} {name}"
    content = "\n".join(
        [
            f"股票：{code} {name}",
            f"日K SXT：{item.get('daily_sxt')}",
            f"15分钟K SXT：{item.get('minute15_sxt')}",
            f"触发时间：{item.get('last_15m_time')}",
            f"数据源：{data_source}",
        ]
    )
    return send_serverchan(title, content)
