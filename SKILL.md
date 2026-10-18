---
name: video-trade-ground-truth
description: Build video ground-truth trade cases from Komjáthy Attila / KA-FXTanoda YouTube videos — fetch the Hungarian auto-caption transcript, locate the real entry and exit moments from the SRT timestamps, save the exact high-resolution frames at those moments, record the exact datetime ranges and instrument/broker symbols, and pull the matching OHLC from MetaTrader5. Use this whenever a task touches video ground truth, research/video_ground_truth, the komjathy_entry_corpus, scraping or mining Komjáthy (FXTanoda) videos, adding a video to a trade corpus, or turning a YouTube video/timestamp into a verified trade — even if the user only names a video id or says "add this video to the corpus".
---

# Video trade ground truth

Turn one Komjáthy Attila video into one verified trade case: the real entry
and exit datetimes, prices and broker symbol, with the exact video frames that
evince them, cross-checked against real MT5 data. This is the pipeline that
produced `research/video_ground_truth/` and `research/komjathy_entry_corpus/`.

Read `references/method.md` before the first build — the parts that are
judgment (which moment is the entry, what the frame's timeframe is, whether a
clock is trustworthy) are rules there, not code here.

## Division of labour — the thing that went wrong before

The original corpus was built by an agent hand-typing `yt-dlp`, `ffmpeg` and
`MetaTrader5` calls for every video, plus hand-writing a `build_chart.py` per
case. That is where the repeated effort and the inconsistencies came from.

This skill splits the work:

- **Deterministic steps go through the bundled scripts** in `scripts/` — video
  probing, the channel census, transcript download, provenance clips, frame
  extraction, MT5 OHLC, folder scaffolding, the trade manifest, and chart
  rendering. Do not re-type these commands per video; call the scripts with
  `<skill>/scripts/*.py --help`.
- **Judgment steps stay with you** — reading the SRT and the frames to decide
  which moment is the entry and which is the exit, reading the timeframe and
  price off the frame, classifying the setup, and recording provenance. The
  scripts narrow where to look; they do not decide.

## Environment check (do this once)

    yt-dlp --version          # or set YT_DLP to its full path
    ffmpeg -version           # or set FFMPEG
    python -c "import MetaTrader5, pandas, plotly"
    python -c "from playwright.sync_api import sync_playwright"   # only for --png

MT5 requires a **running, logged-in MT5 terminal** on the same (Windows)
machine. If it is absent, do not fabricate prices: still produce the
transcript, frames, `case.json` and manifest row, and leave MT5 OHLC and the
chart as `pending`, clearly marked. `mt5_fetch.py` fails loudly, which is the
signal to mark it pending.

If YouTube answers a fetch with a bot check ("Sign in to confirm you're not a
bot"), pass `--cookies-from-browser chrome` (or `firefox`/`edge`) to
`video_fetch.py`; that is the usual fix on a fresh device.

## Workflow

### 1. Pick the video from the census

Build the channel census once (it is the source of truth for order):

    python scripts/video_fetch.py census "https://www.youtube.com/@KA-FXTanoda/videos" \
        --out CHANNEL_CENSUS.tsv

Work strict reverse-chronological order (newest first), no title
pre-filtering — a title does not tell you whether a video contains a dateable
trade, only checking does. Skip videos already present in the target root
(`case_tools.py index` lists them). Probe one video before committing:

    python scripts/video_fetch.py probe "https://www.youtube.com/watch?v=<id>" --out meta.json

### 2. Scaffold the case

    python scripts/case_tools.py new --root <corpus-root> \
        --instrument GOLD --when 2026-06-10_1555 \
        --video-id hTsOgOKq0kM --title "Így skalpolok én a GOLD-on ismét..."

This creates `<root>/<INSTRUMENT>+<when>+<slug>/` with `frames/`, `clips/`,
a `case.json` stub and a `notes.md` skeleton. The `--when` is the **real trade
time**, not the upload date; if you do not know it yet, scaffold after step 4.

### 3. Transcript

    python scripts/video_fetch.py subs "<url>" -o <case-folder>
    python scripts/srt_tool.py to-txt <case-folder>/transcript.hu.srt -o <case-folder>/transcript_clean.txt

If no captions exist, record that and stop the case as `no captions` rather
than guessing — some Komjáthy videos genuinely have none.

### 4. Find the entry and exit moments (judgment + `srt_tool`)

    python scripts/srt_tool.py search <srt> --terms "beszállás,beszállok,nyitva,jang,pipa,kitörés,zárom,zártam,stop,kiléptem" --context 2
    python scripts/srt_tool.py window <srt> --start 03:10 --end 03:40

The hits point at the moments; the surrounding cues and the frames confirm
them. Then grab the exact frames (keep the short clip for provenance):

    python scripts/video_fetch.py clip "<url>" --start 00:02:50 --end 00:03:25 \
        -o <case-folder>/clips/segment_entry.mp4 --video-only
    python scripts/video_fetch.py frame <case-folder>/clips/segment_entry.mp4 \
        --at 00:00:30 -o <case-folder>/frames/entry_frame.jpg

Read the frames multimodally. Take the timeframe from the frame's own ticker
bar, and the price from an order-line label / ticker / gridline — not from
memory of a similar chart.

### 5. Pull real OHLC from MT5

    python scripts/mt5_fetch.py list --match GOLD
    python scripts/mt5_fetch.py pull --symbol GOLD --timeframe M1 \
        --start "2026-06-10 00:00" --end "2026-06-11 00:00" \
        -o <case-folder>/mt5_ohlc_gold_m1_20260610.csv --expect-range 4129,4211

`--expect-range` is the frame's own visible price range; a mismatch means the
symbol or the date is wrong. The script already handles the timezone trap and
the narrow-window-returns-empty trap.

### 6. Render the chart

Write a small JSON spec (see `scripts/render_chart.py`'s docstring for the
fields) and render — this applies the standard layout so no `build_chart.py`
is hand-written per case:

    python scripts/render_chart.py <case-folder>/chart_spec.json -o <case-folder>/chart.html --png <case-folder>/chart_render.png

**Then look at the PNG against the source frame.** A build is not done until
entry/exit price and time, SL, level/zone placement and direction visually
match. Fix and re-render if they do not.

### 7. Record the trade and finish the notes

    python scripts/case_tools.py record --root <corpus-root> --case <folder> \
        --entry-time "2026-06-10 15:55" --entry-price 4160.55 --entry-video-time 00:31:12 \
        --exit-time "2026-06-10 16:40" --exit-price 4175.20 --exit-video-time 01:05:40 \
        --direction long --symbol GOLD --instrument GOLD --timeframe M1 --sl 4145.10 --r 0.8 \
        --classification "S/R zone retest (trend continuation)" \
        --ohlc-csv mt5_ohlc_gold_m1_20260610.csv \
        --entry-frame frames/entry_frame.jpg --exit-frame frames/exit_frame.jpg \
        --tag "entry_price=SOURCE_CONFIRMED" --tag "exit_price=REASONABLE_INTERPRETATION"

`record` rewrites `case.json` and regenerates `<root>/TRADES_INDEX.tsv`, which
is the answer to "the exact datetime ranges and symbols where the trade
happened". Then fill in `notes.md` (entry/exit tables, classification, symbol
resolution, files, still-open items) — the skeleton is already there.

A video with no dateable trade gets a manifest/notes row `no trade — skipped`
with a one-line reason, never a silent omission.

## Output layout

    <root>/<INSTRUMENT>+<YYYY-MM-DD_HHMM>+<slug>/
        case.json               machine-readable trade record + provenance
        notes.md                human-readable, SOURCE_CONFIRMED vs reconstruction
        transcript.hu.srt       Hungarian auto-caption (verbatim)
        transcript_clean.txt    deduplicated plain text
        clips/                  short provenance clips
        frames/entry_frame.jpg, frames/exit_frame.jpg
        mt5_ohlc_<sym>_<tf>_<date>.csv
        chart_spec.json, chart.html, chart_render.png
    <root>/TRADES_INDEX.tsv    one row per trade: times, prices, symbol, R
    <root>/CHANNEL_CENSUS.tsv  id|duration|title, newest first

## Boundary

This skill reads historical data only. It never places an order, modifies a
position, starts a live/shadow worker, or emits alerts — it pulls OHLC, frames
and transcripts. Any real order goes exclusively through the repository's
`execution/` layer and explicit user action.
