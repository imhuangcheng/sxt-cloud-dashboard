from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd


LOGGER = logging.getLogger(__name__)


def save_15m_chart(frame: pd.DataFrame, item: dict, output_path: Path, bars: int = 80) -> Path:
    if frame is None or frame.empty:
        raise ValueError("15分钟K线为空，无法生成截图")
    data = frame.tail(bars).copy()
    required = {"datetime", "open", "high", "low", "close"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"15分钟K线缺少字段: {', '.join(sorted(missing))}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dates = mdates.date2num(pd.to_datetime(data["datetime"]).dt.to_pydatetime())
    fig, ax = plt.subplots(figsize=(12, 6), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#fbfcfe")
    width = 0.009
    for x, (_, row) in zip(dates, data.iterrows()):
        open_price, close_price = float(row["open"]), float(row["close"])
        high, low = float(row["high"]), float(row["low"])
        color = "#d93025" if close_price >= open_price else "#16834b"
        ax.vlines(x, low, high, color=color, linewidth=0.8)
        bottom = min(open_price, close_price)
        height = max(abs(close_price - open_price), 0.0001)
        ax.add_patch(Rectangle((x - width / 2, bottom), width, height, facecolor=color, edgecolor=color, linewidth=0.6))

    code = item.get("code", "")
    ax.set_title(f"{code}\n15m K-line | Daily SXT={item.get('daily_sxt')} | 15m SXT={item.get('minute15_sxt')} | ALERT", loc="left", fontsize=13, fontweight="bold")
    ax.set_ylabel("Price")
    ax.grid(axis="y", alpha=0.22)
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M"))
    fig.autofmt_xdate(rotation=0, ha="center")
    fig.tight_layout()
    fig.savefig(output_path, format="png", bbox_inches="tight")
    plt.close(fig)
    LOGGER.info("saved 15m chart code=%s path=%s", code, output_path)
    return output_path
