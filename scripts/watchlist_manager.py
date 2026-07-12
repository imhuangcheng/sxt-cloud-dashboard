from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CODE_RE = re.compile(r"^\d{6}$")


def normalize_symbol(value: Any) -> str:
    symbol = str(value).strip()
    if not CODE_RE.fullmatch(symbol):
        raise ValueError(f"invalid stock code: {symbol}")
    return symbol


def validate_groups(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
        raise ValueError("groups must be an array")
    groups = []
    ids: set[str] = set()
    names: set[str] = set()
    for raw in payload["groups"]:
        if not isinstance(raw, dict):
            raise ValueError("each group must be an object")
        group_id = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        if not group_id or not name:
            raise ValueError("group id and name are required")
        if group_id in ids:
            raise ValueError(f"duplicate group id: {group_id}")
        if name in names:
            raise ValueError(f"duplicate group name: {name}")
        symbols = raw.get("symbols", [])
        if not isinstance(symbols, list):
            raise ValueError(f"symbols must be an array: {name}")
        normalized = []
        for value in symbols:
            symbol = normalize_symbol(value)
            if symbol not in normalized:
                normalized.append(symbol)
        ids.add(group_id)
        names.add(name)
        groups.append({"id": group_id, "name": name, "symbols": sorted(normalized)})
    return {"version": 1, "updated_at": payload.get("updated_at", ""), "groups": groups}


def all_symbols(payload: dict[str, Any]) -> list[str]:
    return sorted({symbol for group in payload["groups"] for symbol in group["symbols"]})


def symbol_groups(payload: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for group in payload["groups"]:
        for symbol in group["symbols"]:
            result.setdefault(symbol, []).append(group["name"])
    return result


def load_groups(groups_path: Path, watchlist_path: Path) -> dict[str, Any]:
    if groups_path.exists():
        return validate_groups(json.loads(groups_path.read_text(encoding="utf-8")))
    legacy = json.loads(watchlist_path.read_text(encoding="utf-8")) if watchlist_path.exists() else []
    values = legacy.get("watchlist", []) if isinstance(legacy, dict) else legacy
    payload = {"version": 1, "updated_at": "", "groups": [{"id": "default", "name": "默认分组", "symbols": values or []}]}
    payload = validate_groups(payload)
    groups_path.parent.mkdir(parents=True, exist_ok=True)
    if watchlist_path.exists():
        backup = watchlist_path.with_name(watchlist_path.name + ".bak")
        if not backup.exists():
            shutil.copy2(watchlist_path, backup)
    groups_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def sync_legacy(payload: dict[str, Any], watchlist_path: Path) -> list[str]:
    values = all_symbols(payload)
    if watchlist_path.exists():
        current = json.loads(watchlist_path.read_text(encoding="utf-8"))
        if isinstance(current, dict) and "watchlist" in current:
            output: Any = {**current, "watchlist": values}
        else:
            output = values
    else:
        output = {"watchlist": values}
    watchlist_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return values


def touch(payload: dict[str, Any]) -> dict[str, Any]:
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    return payload
