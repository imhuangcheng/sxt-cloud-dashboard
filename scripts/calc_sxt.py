from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


Number = int | float | pd.Series


def _series(value: Number, index: pd.Index | None = None) -> pd.Series:
    if isinstance(value, pd.Series):
        return value
    if index is None:
        raise ValueError("index is required when converting scalar to Series")
    return pd.Series(value, index=index)


def _truthy(value: Number) -> pd.Series:
    if isinstance(value, pd.Series):
        return value.fillna(0).ne(0)
    raise ValueError("condition must be a Series")


def REF(value: pd.Series, n: int | pd.Series = 1) -> pd.Series:
    if isinstance(n, pd.Series):
        result: list[float] = []
        for i, offset in enumerate(n):
            if pd.isna(offset):
                result.append(np.nan)
                continue
            pos = i - int(offset)
            result.append(value.iloc[pos] if 0 <= pos < len(value) else np.nan)
        return pd.Series(result, index=value.index)
    return value.shift(n)


def IF(condition: pd.Series, true_value: Number, false_value: Number) -> pd.Series:
    condition = _truthy(condition)
    index = condition.index
    true_series = _series(true_value, index)
    false_series = _series(false_value, index)
    return pd.Series(np.where(condition.fillna(False), true_series, false_series), index=index)


def MAX(a: Number, b: Number) -> pd.Series:
    a_series = _series(a, b.index if isinstance(b, pd.Series) else None)
    b_series = _series(b, a_series.index)
    return pd.concat([a_series, b_series], axis=1).max(axis=1)


def MIN(a: Number, b: Number) -> pd.Series:
    a_series = _series(a, b.index if isinstance(b, pd.Series) else None)
    b_series = _series(b, a_series.index)
    return pd.concat([a_series, b_series], axis=1).min(axis=1)


def EVERY(condition: pd.Series, n: int) -> pd.Series:
    return _truthy(condition).rolling(n, min_periods=n).sum().eq(n)


def COUNT(condition: pd.Series, n: int | pd.Series) -> pd.Series:
    cond = _truthy(condition).astype(int)
    if isinstance(n, pd.Series):
        result: list[float] = []
        for i, window in enumerate(n):
            start = 0 if pd.isna(window) or int(window) <= 0 else max(0, i - int(window) + 1)
            result.append(float(cond.iloc[start : i + 1].sum()))
        return pd.Series(result, index=condition.index)
    if n == 0:
        return cond.expanding(min_periods=1).sum()
    return cond.rolling(n, min_periods=1).sum()


def SUM(value: pd.Series, n: int | pd.Series) -> pd.Series:
    if isinstance(n, pd.Series):
        result: list[float] = []
        for i, window in enumerate(n):
            start = 0 if pd.isna(window) or int(window) <= 0 else max(0, i - int(window) + 1)
            result.append(float(value.iloc[start : i + 1].sum()))
        return pd.Series(result, index=value.index)
    if n == 0:
        return value.expanding(min_periods=1).sum()
    return value.rolling(n, min_periods=1).sum()


def BARSLAST(condition: pd.Series) -> pd.Series:
    result: list[float] = []
    last_true: int | None = None
    for i, flag in enumerate(_truthy(condition)):
        if flag:
            last_true = i
            result.append(0.0)
        elif last_true is None:
            result.append(np.nan)
        else:
            result.append(float(i - last_true))
    return pd.Series(result, index=condition.index)


def VALUEWHEN(condition: pd.Series, value: pd.Series) -> pd.Series:
    return value.where(_truthy(condition)).ffill()


def FILTERX(condition: pd.Series, n: int | pd.Series) -> pd.Series:
    cond = _truthy(condition).copy()
    result = cond.copy()
    for pos in np.flatnonzero(cond.to_numpy()):
        window = n.iloc[pos] if isinstance(n, pd.Series) else n
        if pd.isna(window) or int(window) <= 0:
            continue
        result.iloc[max(0, pos - int(window)) : pos] = False
    return result


@dataclass(frozen=True)
class SXTResult:
    sxt: int
    signal_text: str
    last_datetime: str


def signal_text(sxt: int | float | None) -> str:
    if sxt is None or pd.isna(sxt):
        return "NO_DATA"
    if int(sxt) == 2:
        return "BUY"
    if int(sxt) > 0:
        return "POSITIVE"
    if int(sxt) < 0:
        return "NEGATIVE"
    return "NEUTRAL"


def calculate_sxt(data: pd.DataFrame, min_bars: int = 80) -> dict[str, Any]:
    required = {"datetime", "open", "high", "low", "close", "volume"}
    if data.empty or not required.issubset(data.columns):
        return {"sxt_value": None, "signal_text": "NO_DATA", "last_datetime": None}
    if len(data) < min_bars:
        last_time = pd.to_datetime(data.iloc[-1]["datetime"]).strftime("%Y-%m-%d %H:%M:%S")
        return {"sxt_value": None, "signal_text": "INSUFFICIENT_DATA", "last_datetime": last_time}

    df = data.copy().reset_index(drop=True)
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if len(df) < min_bars:
        return {"sxt_value": None, "signal_text": "INSUFFICIENT_DATA", "last_datetime": None}

    close = df["close"]
    high = df["high"]
    low = df["low"]
    top = MAX(high, low)
    btm = MIN(high, low)

    dbx = (btm < REF(btm, 1)) & (top < REF(top, 1))
    dbs = (btm > REF(btm, 1)) & (top > REF(top, 1))
    fb1 = (top > REF(top, 1)) & (btm == REF(btm, 1))
    fb2 = (top == REF(top, 1)) & (btm < REF(btm, 1))
    fb3 = (top > REF(top, 1)) & (btm < REF(btm, 1)) & ((top - REF(top, 1)) > (REF(btm, 1) - btm))
    fb4 = (top > REF(top, 1)) & (btm < REF(btm, 1)) & ((top - REF(top, 1)) < (REF(btm, 1) - btm))

    bm0 = IF(dbx, -1, IF(dbs, 1, 0))
    bm1 = IF(bm0.eq(0), IF(fb1 | fb3, 1, IF(fb2 | fb4, -1, bm0)), bm0)
    bm2 = VALUEWHEN(bm1, bm1).fillna(0)

    yjding_ready = REF(EVERY(bm2.eq(1), 3), 1).astype("boolean").fillna(False).astype(bool)
    yjdi_ready = REF(EVERY(bm2.eq(-1), 3), 1).astype("boolean").fillna(False).astype(bool)
    yjding = yjding_ready & bm2.eq(-1)
    yjdi = yjdi_ready & bm2.eq(1)

    yjdingp0 = REF(top, BARSLAST(yjding) + 1)
    yjdip0 = REF(btm, BARSLAST(yjdi) + 1)
    dingdi0 = IF(yjding, yjdingp0, IF(yjdi, yjdip0, 0))
    dingdi1 = VALUEWHEN(dingdi0, dingdi0).fillna(0)
    yjding1 = (dingdi1 > REF(dingdi1, 1)) & yjding
    yjdi1 = (dingdi1 < REF(dingdi1, 1)) & yjdi
    yjding2 = FILTERX(yjding1, BARSLAST(yjdi1))
    yjdi2 = FILTERX(yjdi1, BARSLAST(yjding1))

    db0 = IF(yjdi2, 1, IF(yjding2, -1, 0))
    db1 = VALUEWHEN(db0, db0).fillna(0)

    div0 = IF(yjdi2, dingdi1, 0)
    div1 = VALUEWHEN(div0, div0).fillna(0)
    div2 = IF(div1 < REF(div1, 1), -1, IF(div1 > REF(div1, 1), 1, 0))
    div3 = VALUEWHEN(div2, div2).fillna(0)

    tjyjding = COUNT(yjding, BARSLAST(yjdi2))
    tjyjdi = COUNT(yjdi, BARSLAST(yjding2))
    bldi = tjyjdi * yjdi.astype(int)
    bldi0 = VALUEWHEN(bldi, bldi).fillna(0)
    bldi1 = yjdi2 & bldi.eq(1) & div3.eq(1)
    bldi2 = yjdi2 & (bldi > 1) & div3.eq(1)
    bldi3 = yjdi2 & (bldi0 < REF(bldi0, 1)) & (REF(bldi0, 1) > 1) & div3.eq(1)

    jyd1 = IF(bldi1 | bldi2 | bldi3, 1, IF(yjding2, -1, 0))
    jyd2 = VALUEWHEN(jyd1, jyd1).fillna(0)
    sxt_multiplier = IF((close > yjdingp0) & db1.eq(-1), -1, 1)
    sxt = ((jyd2 + db1) * sxt_multiplier).fillna(0).astype(int)

    last_time = pd.to_datetime(df.iloc[-1]["datetime"]).strftime("%Y-%m-%d %H:%M:%S")
    latest = int(sxt.iloc[-1])
    return {
        "sxt_value": latest,
        "signal_text": signal_text(latest),
        "last_datetime": last_time,
    }
