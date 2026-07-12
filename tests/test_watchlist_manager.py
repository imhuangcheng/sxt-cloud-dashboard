import json

from scripts.watchlist_manager import all_symbols, load_groups, symbol_groups, validate_groups


def test_cross_group_symbols_are_deduplicated():
    payload = validate_groups({"groups": [
        {"id": "ai", "name": "AI", "symbols": ["600601", "002709", "002709"]},
        {"id": "watch", "name": "观察池", "symbols": ["600601"]},
    ]})
    assert all_symbols(payload) == ["002709", "600601"]
    assert symbol_groups(payload)["600601"] == ["AI", "观察池"]


def test_legacy_watchlist_is_migrated_and_backed_up(tmp_path):
    legacy = tmp_path / "watchlist.json"
    groups = tmp_path / "watchlist_groups.json"
    legacy.write_text(json.dumps({"watchlist": ["002709"]}), encoding="utf-8")
    payload = load_groups(groups, legacy)
    assert payload["groups"][0]["name"] == "默认分组"
    assert (tmp_path / "watchlist.json.bak").exists()


def test_empty_groups_are_allowed():
    payload = validate_groups({"groups": [{"id": "empty", "name": "观察池", "symbols": []}]})
    assert all_symbols(payload) == []
