from __future__ import annotations

import logging
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover - fallback for very small local runtimes
    requests = None


LOGGER = logging.getLogger(__name__)

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
TENCENT_DAILY_URL = "http://ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_MINUTE_URL = "http://ifzq.gtimg.cn/appstock/app/kline/mkline"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
    "Referer": "https://gu.qq.com/",
}


@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    market: str
    supported: bool = True
    reason: str = ""

    @property
    def display_name(self) -> str:
        return self.name or "-"


def normalize_stock(raw: dict[str, Any] | str) -> Stock:
    if isinstance(raw, str):
        code = raw.strip()
        name = ""
        market = ""
    else:
        code = str(raw.get("code", "")).strip()
        name = str(raw.get("name", "") or "").strip()
        market = str(raw.get("market", "") or "").strip().lower()

    if not code:
        return Stock(code="", name=name, market=market, supported=False, reason="missing code")

    if not market:
        if code.startswith("6"):
            market = "sh"
        elif code.startswith(("0", "2", "3")):
            market = "sz"
        elif code.startswith(("4", "8")):
            market = "unsupported"
        else:
            market = "unsupported"

    if market not in {"sh", "sz"}:
        return Stock(code=code, name=name, market=market, supported=False, reason="unsupported market")

    return Stock(code=code, name=name, market=market)


def _tencent_symbol(stock: Stock) -> str:
    return f"{stock.market}{stock.code}"


def _loads_json_or_jsonp(body: str) -> dict[str, Any]:
    text = body.strip()
    if "=" in text and not text.startswith("{"):
        text = text.split("=", 1)[1]
    return json.loads(text)


def _get_json(url: str, params: dict[str, str], timeout: int) -> dict[str, Any]:
    if requests is not None:
        session = requests.Session()
        response = session.get(url, params=params, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        return _loads_json_or_jsonp(response.text)

    request = Request(f"{url}?{urlencode(params)}", headers=HEADERS)
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return _loads_json_or_jsonp(body)


def _get_text(url: str, timeout: int, encoding: str = "utf-8") -> str:
    if requests is not None:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        response.encoding = encoding
        return response.text

    request = Request(url, headers=HEADERS)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode(encoding, errors="replace")


def fetch_tencent_quote(stock: Stock, timeout: int = 8) -> dict[str, Any]:
    if not stock.supported:
        return {}
    symbol = _tencent_symbol(stock)
    body = _get_text(f"{TENCENT_QUOTE_URL}{symbol}", timeout=timeout, encoding="gbk")
    for line in body.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=", 1)[0].split("_")[-1]
        if key != symbol:
            continue
        values = line.split('"', 2)[1].split("~")
        if len(values) < 3:
            continue
        return {
            "name": values[1].strip(),
            "code": values[2].strip(),
        }
    return {}


def fetch_stock_name(stock: Stock, timeout: int = 8) -> str:
    if stock.name:
        return stock.name
    if not stock.supported:
        return ""
    try:
        quote = fetch_tencent_quote(stock, timeout=timeout)
        name = str(quote.get("name") or "").strip()
        return "" if name == "-" else name
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("stock name lookup failed for %s: %s", stock.code, exc)
        return ""


def _normalize_rows(rows: list[list[Any]], datetime_format: str | None = None) -> pd.DataFrame:
    parsed = []
    for parts in rows:
        if len(parts) < 6:
            continue
        parsed.append(
            {
                "datetime": parts[0],
                "open": parts[1],
                "close": parts[2],
                "high": parts[3],
                "low": parts[4],
                "volume": parts[5],
            }
        )

    df = pd.DataFrame(parsed)
    if df.empty:
        return df
    df["datetime"] = pd.to_datetime(df["datetime"], format=datetime_format, errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=["datetime", "open", "high", "low", "close"]).reset_index(drop=True)


def fetch_a_stock_data_kline(stock: Stock, period: str, limit: int = 260, timeout: int = 12) -> pd.DataFrame:
    symbol = _tencent_symbol(stock)
    if period == "daily":
        payload = _get_json(
            TENCENT_DAILY_URL,
            {"_var": "testKline", "param": f"{symbol},day,,,{limit},qfq"},
            timeout,
        )
        stock_data = (payload.get("data") or {}).get(symbol) or {}
        rows = stock_data.get("qfqday") or stock_data.get("day") or []
        df = _normalize_rows(rows, "%Y-%m-%d")
    elif period == "15m":
        payload = _get_json(TENCENT_MINUTE_URL, {"param": f"{symbol},m15,,{limit}"}, timeout)
        stock_data = (payload.get("data") or {}).get(symbol) or {}
        rows = stock_data.get("m15") or []
        df = _normalize_rows(rows, "%Y%m%d%H%M")
    else:
        raise ValueError(f"unsupported period: {period}")

    if df.empty:
        raise RuntimeError(f"empty Tencent kline data for {stock.code} {period}")
    LOGGER.info("fetched %s %s bars=%s source=a-stock-data/tencent", stock.code, period, len(df))
    return df


def fetch_kline(stock: Stock, period: str, limit: int = 260, timeout: int = 12) -> pd.DataFrame:
    if not stock.supported:
        raise ValueError(stock.reason or "unsupported stock")

    return fetch_a_stock_data_kline(stock, period, limit=limit, timeout=timeout)


def fetch_daily(stock: Stock, limit: int = 260) -> pd.DataFrame:
    return fetch_kline(stock, "daily", limit=limit)


def fetch_15m(stock: Stock, limit: int = 260) -> pd.DataFrame:
    return fetch_kline(stock, "15m", limit=limit)
