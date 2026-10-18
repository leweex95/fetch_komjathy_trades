# fetch_komjathy_trades

An OpenCode / Claude Code **skill** for turning a Komjáthy Attila (FXTanoda)
YouTube video into a verified, checkable trade case: the real entry and exit
datetimes, prices and broker symbol, with the exact high-resolution video
frames that prove them, cross-checked against real MetaTrader 5 data.

It is the reusable form of the pipeline behind a hand-built research corpus:
previously an agent re-typed `yt-dlp`, `ffmpeg` and `MetaTrader5` calls for
every video and hand-wrote a chart script per case. Those repeated operations
are now scripts; only the judgment stays with the model.

## What a build produces

```
<case>/<INSTRUMENT>+<YYYY-MM-DD_HHMM>+<slug>/
    case.json                 machine-readable trade record + provenance labels
    notes.md                  human-readable: entry/exit tables, classification, open questions
    transcript.hu.srt         Hungarian auto-caption, verbatim
    transcript_clean.txt      deduplicated plain text
    clips/                    short provenance clips around entry/exit
    frames/entry_frame.jpg    the entry moment, full source resolution
    frames/exit_frame.jpg     the exit moment
    mt5_ohlc_<sym>_<tf>_<date>.csv
    chart_spec.json           the small render spec
    chart.html                standard layout: WHY panel, context minis, marked entry/exit
    chart_render.png          the verification render
<root>/TRADES_INDEX.tsv       one row per trade: times, prices, symbol, R
<root>/CHANNEL_CENSUS.tsv     id | duration | title, newest first
```

## Requirements

| Need | Why | Notes |
|---|---|---|
| `yt-dlp` | video, transcript, clip download | `pip install yt-dlp` or a release binary |
| `ffmpeg` | frame extraction, subtitle/SRT conversion | must be on `PATH` |
| `pandas`, `plotly` | OHLC + chart | `pip install -r requirements.txt` |
| `MetaTrader5` | real OHLC | **Windows only**, and needs a running, logged-in MT5 terminal. The package is an RPC client, not a data source. |
| `playwright` | `--png` render of `chart.html` | optional; `playwright install chromium` once |

Override the binary locations with the `YT_DLP` and `FFMPEG` environment
variables if they are not on `PATH`.

### When MT5 is unavailable

The build degrades gracefully: transcript, frames, `case.json` and the manifest
row are still produced, and the OHLC/chart step is marked `pending` so it can be
filled in later on a machine with the terminal. Prices are never invented.

## Install as a skill

The repository root *is* the skill (it contains `SKILL.md`).

**OpenCode** — clone it into your skills directory:

```bash
git clone https://github.com/leweex95/fetch_komjathy_trades.git \
  .opencode/skills/video-trade-ground-truth
```

**Claude Code** — same thing under `.claude/skills/`:

```bash
git clone https://github.com/leweex95/fetch_komjathy_trades.git \
  .claude/skills/video-trade-ground-truth
```

The agent then picks it up from the `name`/`description` frontmatter in
`SKILL.md`. Nothing imports the host repository, so the skill works in any
project.

## Quickstart

```bash
# 1. one-off: the channel census (newest first)
python scripts/video_fetch.py census "https://www.youtube.com/@KA-FXTanoda/videos" \
    --out CHANNEL_CENSUS.tsv

# 2. probe the video and scaffold its case folder
python scripts/video_fetch.py probe "https://www.youtube.com/watch?v=<id>" --out meta.json
python scripts/case_tools.py new --root research/video_ground_truth \
    --instrument GOLD --when 2026-06-10_1555 --video-id <id> --title "<title>"

# 3. transcript, then find the moments
python scripts/video_fetch.py subs "https://www.youtube.com/watch?v=<id>" -o <case>
python scripts/srt_tool.py to-txt <case>/transcript.hu.srt -o <case>/transcript_clean.txt
python scripts/srt_tool.py search <case>/transcript.hu.srt \
    --terms "beszállás,beszállok,nyitva,jang,pipa,kitörés,zárom,zártam,stop,kiléptem" --context 2

# 4. frames at the moments you identified
python scripts/video_fetch.py clip "<url>" --start 00:02:50 --end 00:03:25 \
    -o <case>/clips/segment_entry.mp4 --video-only
python scripts/video_fetch.py frame <case>/clips/segment_entry.mp4 \
    --at 00:00:30 -o <case>/frames/entry_frame.jpg

# 5. real OHLC; --expect-range is the frame's own visible price axis
python scripts/mt5_fetch.py list --match GOLD
python scripts/mt5_fetch.py pull --symbol GOLD --timeframe M1 \
    --start "2026-06-10 00:00" --end "2026-06-11 00:00" \
    -o <case>/mt5_ohlc_gold_m1_20260610.csv --expect-range 4129,4211

# 6. render and LOOK at the PNG against the source frame
python scripts/render_chart.py <case>/chart_spec.json -o <case>/chart.html \
    --png <case>/chart_render.png

# 7. record the trade window + symbol, regenerate the manifest
python scripts/case_tools.py record --root research/video_ground_truth --case <folder> \
    --entry-time "2026-06-10 15:55" --entry-price 4160.55 \
    --exit-time "2026-06-10 16:40"  --exit-price 4175.20 \
    --direction long --symbol GOLD --instrument GOLD --timeframe M1 \
    --sl 4145.10 --r 0.8 --classification "S/R zone retest (trend continuation)" \
    --tag entry_price=SOURCE_CONFIRMED --tag exit_price=REASONABLE_INTERPRETATION
```

Every script has `--help`. `SKILL.md` holds the workflow; `references/method.md`
holds the judgment rules (provenance labels, why on-screen clocks are not
evidence, reading the timeframe off the frame, JIN/JANG classification
discipline).

## The three traps the code already handles

1. **Timezone.** MT5 labels bars in broker server time treated as UTC, but the
   `MetaTrader5` package interprets a *naive* datetime in the PC's local
   timezone. Naive bounds shift the whole window by the PC's UTC offset. All
   bounds are tagged UTC.
2. **`copy_rates_range` returns empty for narrow windows** even when the data
   exists. The pull widens to whole calendar days and filters with pandas.
3. **Symbol names are case-sensitive and suffixed** (`EURUSD.a`, `#GER40_U26`),
   and `symbols_get()` lists names `symbol_select` may then refuse. The pull
   cross-checks the returned price range against the frame's own price axis.

## Scope and boundary

This tool reads **historical** data only. It never places an order, modifies a
position, runs a live/shadow worker or emits alerts — it downloads transcripts,
extracts frames and reads OHLC. Trading is out of scope by design.

Provenance labels (`SOURCE_CONFIRMED` vs `REASONABLE_INTERPRETATION` vs
unknown) exist so a reconstructed value can never be mistaken for something
read off the screen.
