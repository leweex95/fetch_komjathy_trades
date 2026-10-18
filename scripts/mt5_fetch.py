#!/usr/bin/env python3
"""Standalone MT5 OHLC pull for video-ground-truth builds.

DATA ONLY. This never places an order or touches a position -- it reads
historical bars and writes a CSV. The `MetaTrader5` package is a thin RPC
client: it needs a running, logged-in MT5 terminal on the same Windows
machine, so on a device without the terminal these commands fail loudly and
the build marks MT5 OHLC as "pending" instead of guessing prices.

Three hard-won lessons from the original corpus are encoded here, because
each one silently corrupted a build before it was understood:

1. Timezone. MT5 labels bars with the BROKER's server time treated as if it
   were UTC, but the `MetaTrader5` package interprets a NAIVE datetime in the
   PC's LOCAL timezone. A naive bound therefore shifts the whole range by the
   PC's UTC offset (measured: a UTC+2 machine got a window 2 h early at both
   ends). Every bound is tagged UTC here.
2. `copy_rates_range` can return EMPTY for a narrow window even when the
   symbol has valid bars in that range. Fix: widen to whole calendar days and
   filter with pandas, rather than believing the empty answer.
3. Symbol names are case-SENSITIVE, may carry broker/contract suffixes
   ('EURUSD.a', '#GER40_U26'), and the terminal's catalogue lists names
   `symbol_select` then refuses. Resolve by substring against `symbols_get()`
   and cross-check the returned price range against the frame's own price
   axis before committing to a symbol.
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timedelta

import pandas as pd

_TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
_ATTR = {tf: f"TIMEFRAME_{tf}" for tf in _TIMEFRAMES}


def _import_mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError:
        sys.exit(
            "ERROR: the MetaTrader5 package is not installed. Install it with "
            "`pip install MetaTrader5` (Windows only, needs a local MT5 terminal)."
        )
    return mt5


class _Session:
    """initialize -> yield -> always shutdown."""

    def __enter__(self):
        self.mt5 = _import_mt5()
        if not self.mt5.initialize():
            code, message = self.mt5.last_error()
            sys.exit(
                f"ERROR: MT5 initialize() failed ({code}: {message}). A running, "
                f"logged-in MT5 terminal is required on this machine."
            )
        return self.mt5

    def __exit__(self, *exc):
        self.mt5.shutdown()
        return False


def _utc_bound(value) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime()


def _select(mt5, symbol: str) -> None:
    if mt5.symbol_select(symbol, True):
        return
    code, message = mt5.last_error()
    sys.exit(
        f"ERROR: symbol_select({symbol!r}) failed ({code}: {message}). The name is "
        f"either not offered by this account or not exactly right -- lookup is "
        f"case-sensitive and suffixes count. Find the terminal's spelling with: "
        f"mt5_fetch.py list --match {symbol.lstrip('#')[:4].upper()}"
    )


def cmd_list(args: argparse.Namespace) -> None:
    with _Session() as mt5:
        names = sorted(s.name for s in (mt5.symbols_get() or []))
    if args.match:
        needle = args.match.lower()
        names = [n for n in names if needle in n.lower()]
    for n in names:
        print(n)
    print(f"# {len(names)} match(es)", file=sys.stderr)


def _fetch(mt5, symbol: str, timeframe: str, start, end) -> pd.DataFrame:
    rates = mt5.copy_rates_range(symbol, getattr(mt5, _ATTR[timeframe]), _utc_bound(start), _utc_bound(end))
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates).rename(columns={"tick_volume": "volume"})
    df["time"] = pd.to_datetime(df["time"], unit="s")
    cols = ["time", "open", "high", "low", "close", "volume"]
    if "spread" in df.columns:
        cols.append("spread")
    return df[cols]


def cmd_pull(args: argparse.Namespace) -> None:
    if args.timeframe not in _TIMEFRAMES:
        sys.exit(f"ERROR: unknown timeframe {args.timeframe!r}; expected one of {_TIMEFRAMES}")
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    with _Session() as mt5:
        _select(mt5, args.symbol)
        # Attempt 1: the exact requested window.
        df = _fetch(mt5, args.symbol, args.timeframe, start, end)
        used_wide = False
        if df.empty:
            # Attempt 2: whole calendar days (+pad) then filter -- the narrow
            # window can be refused even when the data exists.
            pad = pd.Timedelta(days=args.pad_days)
            lo = start.normalize() - pad
            hi = end.normalize() + pd.Timedelta(days=1) + pad
            df = _fetch(mt5, args.symbol, args.timeframe, lo, hi)
            used_wide = True
        if df.empty:
            sys.exit(
                f"ERROR: MT5 returned no bars for {args.symbol} {args.timeframe} "
                f"between {start} and {end} even after widening. Check the symbol "
                f"and that the range has trading hours."
            )
        df = df[(df["time"] >= start) & (df["time"] <= end)].reset_index(drop=True)
    df.to_csv(args.out, index=False)
    note = " (after widening to full days + filtering)" if used_wide else ""
    print(
        f"wrote {args.out}: {len(df)} {args.symbol} {args.timeframe} bars "
        f"{df['time'].min() if len(df) else '-'} .. {df['time'].max() if len(df) else '-'}{note}"
    )
    if args.expect_range:
        lo, hi = (float(x) for x in args.expect_range.split(","))
        got = (df["low"].min(), df["high"].max()) if len(df) else (math.nan, math.nan)
        ok = got[0] <= hi and got[1] >= lo
        print(
            f"# price-axis cross-check: frame shows {lo}..{hi}, data spans "
            f"{got[0]}..{got[1]} -> {'consistent' if ok else 'MISMATCH -- wrong symbol or range?'}",
            file=sys.stderr,
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("list", help="symbols offered by this terminal (optionally filtered)")
    sp.add_argument("--match", help="case-insensitive substring, e.g. GOLD")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("pull", help="write OHLC bars for one symbol/timeframe/range to CSV")
    sp.add_argument("--symbol", required=True)
    sp.add_argument("--timeframe", required=True, help=f"one of {_TIMEFRAMES}")
    sp.add_argument("--start", required=True, help="broker server time, e.g. '2026-09-07 12:00'")
    sp.add_argument("--end", required=True)
    sp.add_argument("-o", "--out", required=True, help="output CSV path")
    sp.add_argument("--pad-days", type=int, default=1, help="days added when widening an empty narrow window")
    sp.add_argument("--expect-range", metavar="LOW,HIGH",
                    help="frame's visible price range; warns if the data does not overlap it")
    sp.set_defaults(func=cmd_pull)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
