"""Shared HTML page template for video-ground-truth charts.

Layout (introduced 2026-09-12, applies to all builds going forward):
a full-width header (title + subtitle + YouTube deep-link) sits above a
two-column row -- a fixed-width left column (WHY panel, then one or more
small higher-timeframe context charts of the same width, stacked below it)
next to the main chart on the right. The header owns the top-left corner so
the title is never pushed right by the WHY panel; the YouTube link lives in
the header, not inside the WHY panel, since it's about the whole trade, not
specifically the entry/exit reasoning.

Context charts (updated 2026-09-12): there are normally two, one timeframe
coarser than the main chart and one two timeframes coarser (M1 main -> M5 +
M15 context; M15 main -> H1 + H4 context), each replaying the same S/R
levels/zones drawn on the main chart so the setup stays recognizable zoomed
out, not just the candles.

Used by every build_chart.py in this directory. Keep this module free of
per-trade content -- it only assembles markup around content each build
script provides.

Each build_chart.py lives one directory below this file and runs with that
subdirectory as its working directory, so it needs this file's directory on
sys.path before importing it:

    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from _chart_template import render_page, build_mini_chart
"""
import pandas as pd
import plotly.graph_objects as go


def resample_ohlc(df, rule):
    """Resample an OHLC dataframe (columns: time, open, high, low, close) to
    a coarser timeframe, e.g. rule='5min' (M1->M5) or rule='1h' (M15->H1)."""
    return (
        df.set_index("time")
        .resample(rule)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
        .reset_index()
    )


def build_mini_chart(df, rule, label, entry_time, exit_time=None, height=200, levels=None):
    """Small, zoomed-out candlestick chart at one timeframe coarser than the
    main chart, over the full range of `df` -- gives the "longer-term trend"
    context that the (now narrow) main chart intentionally leaves out.

    levels: optional list of the same S/R levels/zones drawn on the main
        chart, so they stay visible here too. Each entry is either
        {"type": "line", "price": ..., "color": ..., "dash": "dot"} or
        {"type": "zone", "top": ..., "bottom": ..., "color": "rgba(...)"}.

    Plotly.js itself is loaded once, from <head> (see render_page) -- both
    this figure and the main chart's figure must be rendered with
    include_plotlyjs=False, or the CDN script would load twice."""
    mdf = resample_ohlc(df, rule)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=mdf["time"], open=mdf["open"], high=mdf["high"], low=mdf["low"], close=mdf["close"],
        name=label, showlegend=False,
    ))
    for lv in (levels or []):
        if lv["type"] == "zone":
            fig.add_hrect(y0=lv["bottom"], y1=lv["top"],
                           fillcolor=lv.get("color", "rgba(0,180,220,0.20)"),
                           line_width=1, line_color=lv.get("line_color", "rgba(0,140,180,0.8)"))
        elif lv["type"] == "line":
            fig.add_hline(y=lv["price"], line_width=1,
                           line_dash=lv.get("dash", "dot"), line_color=lv.get("color", "red"))
    fig.add_vline(x=entry_time, line_width=1, line_dash="dot", line_color="green")
    if exit_time is not None:
        fig.add_vline(x=exit_time, line_width=1, line_dash="dot", line_color="purple")
    fig.update_layout(
        title=dict(text=label, font=dict(size=11), x=0.02, y=0.97, xanchor="left", yanchor="top"),
        xaxis_rangeslider_visible=False,
        margin=dict(l=4, r=4, t=22, b=18),
        showlegend=False,
        font=dict(size=9),
    )
    fig.update_yaxes(showticklabels=True, tickfont=dict(size=8))
    fig.update_xaxes(tickfont=dict(size=8))
    return fig.to_html(full_html=False, include_plotlyjs=False,
                        default_height=f"{height}px", config={"responsive": True, "displayModeBar": False})


def render_page(*, page_title, subtitle_html, video_url, video_label,
                 why_panel_body_html, main_plot_div, mini_plot_divs,
                 panel_width=380):
    """Assemble the full chart.html page.

    why_panel_body_html: inner HTML for the WHY panel (ENTRY/EXIT SIGNAL
        text), WITHOUT the youtube link paragraph and WITHOUT the wrapping
        <div class="why-panel">...</div> -- this function adds that wrapper.
    main_plot_div: pre-rendered `fig.to_html(full_html=False, ...)` string
        for the main chart.
    mini_plot_divs: list of pre-rendered context-chart div strings (see
        build_mini_chart), stacked below the WHY panel in source order --
        normally [timeframe+1, timeframe+2].
    """
    mini_charts_html = "".join(f'<div class="mini-chart">\n{d}\n</div>\n' for d in mini_plot_divs)
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; }}
  .header {{ padding: 14px 16px 6px 16px; }}
  .header h1 {{ margin: 0 0 4px 0; font-size: 19px; }}
  .header .subtitle {{ font-size: 13px; color: #333; line-height: 1.4; }}
  .header .video-link {{ font-size: 13px; margin-top: 6px; }}
  .header .video-link a {{ text-decoration: none; color: #0645ad; font-weight: bold; }}
  .layout {{ display: flex; align-items: flex-start; }}
  .left-col {{
    flex: 0 0 {panel_width}px; width: {panel_width}px; box-sizing: border-box;
    margin: 0 0 16px 16px; display: flex; flex-direction: column; gap: 12px;
  }}
  .why-panel {{
    background: #fffff0; border: 1px solid #000; border-radius: 4px;
    padding: 12px; font-size: 12px; line-height: 1.45; box-sizing: border-box;
  }}
  .why-panel p {{ margin: 10px 0 0 0; }}
  .mini-chart {{
    border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box;
    overflow: hidden;
  }}
  .chart-container {{ flex: 1 1 auto; min-width: 0; }}
</style></head>
<body>
<div class="header">
  <h1>{page_title}</h1>
  <div class="subtitle">{subtitle_html}</div>
  <div class="video-link"><a href="{video_url}" target="_blank" rel="noopener">&#9654; watch on YouTube ({video_label})</a></div>
</div>
<div class="layout">
<div class="left-col">
<div class="why-panel">
{why_panel_body_html}
</div>
{mini_charts_html}</div>
<div class="chart-container">
{main_plot_div}
</div>
</div>
</body></html>
"""
