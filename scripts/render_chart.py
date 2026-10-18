#!/usr/bin/env python3
"""Render a standardised chart.html (+ optional PNG) from a small JSON spec.

Standalone: needs pandas + plotly (and playwright only for --png).

The corpus's layout rules were re-derived by hand for every one of the ~11
builds, and several were rebuilt more than once because a rule was missed
(labels sitting on top of the candles, missing mini-charts, an S/R level
described in text instead of drawn). Encoding them here means a build emits a
spec -- which only contains what is actually known about the trade -- and the
layout is right by construction:

  - full-width header owns the title/subtitle and the YouTube deep-link;
  - WHY panel + context mini-charts in a fixed left column, main chart right;
  - entry/exit marked at exact price/time with data-coordinate labels,
    headroom above the candles, arrows, staggered so they do not collide;
  - every S/R level/zone drawn on the main chart AND on both mini-charts;
  - main chart window kept to roughly the span actually visible on the
    source frame (the spec supplies it) instead of an arbitrary range.

Spec (JSON) — only fields that apply:
{
  "page_title": "...", "subtitle_html": "...",
  "video_url": "...", "video_label": "00:03:20",
  "why_entry": "support/resistance zone ... SHORT 53118.76 on the retest.",
  "why_exit": "MA(5)/MA(21) close-cross ... closed for 0.9R.",
  "ohlc_path": "mt5_ohlc_us30_m1_20260907.csv",
  "timeframe": "M1", "symbol_label": "US30/Dow Jones",
  "entry": {"time": "2026-09-07 17:42:00", "price": 53118.76, "side": "short"},
  "exit":  {"time": "2026-09-07 17:50:00", "price": 53101.22, "r": 0.9},
  "stop": 53138.25,
  "levels": [{"type":"zone","top":53138.25,"bottom":53129.0}, {"type":"line","price":53138.25}],
  "window": {"start": "2026-09-07 12:00", "end": "2026-09-07 18:00"},
  "context": ["5min", "15min"]     // optional; defaults from `timeframe`
}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import pandas as pd
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _chart_template import render_page, build_mini_chart  # noqa: E402

# main timeframe -> two coarser context rules, per the corpus layout rule
_DEFAULT_CONTEXT = {
    "M1": ["5min", "15min"],
    "M5": ["15min", "1h"],
    "M15": ["1h", "4h"],
    "M30": ["4h", "1D"],
    "H1": ["4h", "1D"],
    "H4": ["1D", "1W"],
    "D1": ["1W", "1ME"],
}


def _levels_from_spec(spec: dict) -> list[dict]:
    levels = list(spec.get("levels") or [])
    if spec.get("stop") is not None and not any(
        lv.get("type") == "line" and lv.get("price") == spec["stop"] for lv in levels
    ):
        levels.append({"type": "line", "price": spec["stop"], "color": "red", "dash": "dot"})
    return levels


def build(spec: dict) -> str:
    df = pd.read_csv(spec["ohlc_path"], parse_dates=["time"]).sort_values("time").reset_index(drop=True)
    entry = pd.Timestamp(spec["entry"]["time"])
    exit_ = pd.Timestamp(spec["exit"]["time"]) if spec.get("exit") else None
    window = spec.get("window") or {}
    lo = pd.Timestamp(window.get("start", df["time"].min()))
    hi = pd.Timestamp(window.get("end", df["time"].max()))
    plot_df = df[(df["time"] >= lo) & (df["time"] <= hi)].copy()
    if plot_df.empty:
        sys.exit(f"ERROR: no bars between {lo} and {hi}; widen `window` or fetch more data")

    levels = _levels_from_spec(spec)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=plot_df["time"], open=plot_df["open"], high=plot_df["high"],
        low=plot_df["low"], close=plot_df["close"],
        name=f"{spec.get('symbol_label', '')} {spec.get('timeframe', '')} (MT5)",
    ))
    for lv in levels:
        if lv["type"] == "zone":
            fig.add_hrect(y0=lv["bottom"], y1=lv["top"],
                          fillcolor=lv.get("color", "rgba(0,180,220,0.20)"),
                          line_width=1, line_color=lv.get("line_color", "rgba(0,140,180,0.8)"),
                          annotation_text=lv.get("label", ""), annotation_position="top left")
        elif lv["type"] == "line":
            fig.add_hline(y=lv["price"], line_width=1, line_dash=lv.get("dash", "dot"),
                          line_color=lv.get("color", "red"),
                          annotation_text=lv.get("label", f"{lv['price']}"), annotation_position="right")

    # Labels sit ABOVE the candles, in data coordinates, with arrows -- never a
    # box on top of price. Entry label is staggered left, exit right, so the
    # two never overlap even on a short trade.
    span = max(plot_df["time"].max() - plot_df["time"].min(), pd.Timedelta(minutes=30))
    label_y = plot_df["high"].max() + (plot_df["high"].max() - plot_df["low"].min()) * 0.06
    offset = span * 0.22

    def _mark(ts, price, text, color, xanchor, x_off):
        fig.add_shape(type="line", x0=ts, x1=ts, y0=0, y1=1, yref="paper",
                      line=dict(width=1, dash="dot", color=color))
        fig.add_annotation(
            x=ts, y=price, ax=ts + x_off, ay=label_y, axref="x", ayref="y",
            text=text, showarrow=True, arrowhead=2, arrowwidth=1.5, arrowcolor=color,
            bgcolor=color, font=dict(color="white", size=12),
            xanchor=xanchor, yanchor="bottom", borderwidth=1,
        )

    side = (spec["entry"].get("side") or "").upper()
    _mark(entry, spec["entry"]["price"],
          f"ENTRY ({side}) {spec['entry']['price']}<br>{entry:%Y-%m-%d %H:%M}",
          "rgba(180,0,0,0.92)", "right", -offset)
    if exit_ is not None:
        r = spec["exit"].get("r")
        rtxt = f", {r}R" if r is not None else ""
        _mark(exit_, spec["exit"]["price"],
              f"EXIT {spec['exit']['price']}<br>{exit_:%Y-%m-%d %H:%M}{rtxt}",
              "rgba(140,0,180,0.92)", "left", +offset)

    fig.update_layout(
        xaxis_title="time (MT5/broker server time)", yaxis_title="price",
        yaxis=dict(range=[plot_df["low"].min(), label_y + (label_y - plot_df["low"].min()) * 0.12]),
        xaxis_rangeslider_visible=False,
        margin=dict(l=70, t=20, b=80, r=90),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0),
        autosize=True,
    )
    main_div = fig.to_html(full_html=False, include_plotlyjs=False,
                           default_height="850px", config={"responsive": True})

    rules = spec.get("context") or _DEFAULT_CONTEXT.get(spec.get("timeframe", "M1"), ["15min", "1h"])
    mini_divs = [
        build_mini_chart(df, rule, f"{spec.get('symbol_label', '')} {rule} -- context",
                         entry, exit_, levels=levels)
        for rule in rules
    ]

    why = (f"<b>ENTRY SIGNAL:</b> {spec.get('why_entry', '')}"
           f"<p><b>EXIT SIGNAL:</b> {spec.get('why_exit', '')}</p>")
    return render_page(
        page_title=spec["page_title"],
        subtitle_html=spec.get("subtitle_html", ""),
        video_url=spec.get("video_url", ""),
        video_label=spec.get("video_label", ""),
        why_panel_body_html=why,
        main_plot_div=main_div,
        mini_plot_divs=mini_divs,
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("spec", help="path to the JSON spec")
    p.add_argument("-o", "--out", default="chart.html")
    p.add_argument("--png", help="also render a PNG here (needs playwright chromium)")
    args = p.parse_args()
    # utf-8-sig tolerates the BOM PowerShell's `Set-Content -Encoding UTF8`
    # writes; plain utf-8 would fail on every spec authored that way.
    with open(args.spec, encoding="utf-8-sig") as fh:
        spec = json.load(fh)
    # Paths in the spec are relative to the case folder (the spec's own dir).
    case_dir = os.path.dirname(os.path.abspath(args.spec))
    if not os.path.isabs(spec.get("ohlc_path", "")):
        spec["ohlc_path"] = os.path.join(case_dir, spec["ohlc_path"])
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(build(spec))
    print(f"wrote {args.out}")
    if args.png:
        shot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_screenshot.py")
        subprocess.run([sys.executable, shot, args.out, args.png], check=True)


if __name__ == "__main__":
    main()
