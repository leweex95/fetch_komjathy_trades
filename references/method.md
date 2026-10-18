# Method and standing rules

distilled from the original corpus: `research/video_ground_truth/MASTER_INDEX.md`,
`.claude/agents/video-ground-truth-builder.md`, and the per-case `notes.md`
files. Read this before your first build; it is the part that judgment, not a
script, has to get right.

## The question

For one Komjáthy Attila video: **what real trade is narrated, and what are its
exact entry and exit datetimes, prices, and broker symbol?** The deliverable is
a case folder that a reader can check against the video, plus one row in a
machine-readable manifest of trade windows.

## Provenance is the whole point

Every significant value carries a label, recorded in `case.json`'s
`provenance` map and in prose in `notes.md`:

- `SOURCE_CONFIRMED` — read directly off a frame's gridline/ticker/order-line
  label, or stated verbatim in the transcript.
- `REASONABLE_INTERPRETATION` — a mechanical reconstruction that the source
  does not state (e.g. an exit price back-calculated from an on-screen `0.9R`
  and a confirmed stop). Never present it as if it were read off the screen.
- `EXPERIMENTAL_HYPOTHESIS` / `UNKNOWN` — say so rather than guess.

Never silently convert an interpretation into a fact. If a computed value
disagrees with what is narrated, the real moment has not been found yet — keep
looking, do not ship the computed number with a hedge.

## Clocks are not evidence

An on-screen wall-clock, a status-bar `yyyy.mm.dd hh:mm`, an "it's now…"
remark, or the upload date is **not** automatically the real MT5 timestamp.
Cross-check against real price structure first. Two documented traps in the
corpus: a status bar that read ~5 h off, and an on-screen clock reading ~1 h
behind broker time. The reliable anchors are:

- the **forming-bar ticker OHLC fingerprint** — the top-left ticker shows the
  OHLC of the still-forming bar; its Open is fixed, so match Open against real
  MT5 bars and check that the frame's partial H/L/C are consistent with being a
  mid-formation snapshot of that bar;
- **price-axis / level matching** — the frame's visible levels and window shape
  against real bars;
- a value printed on screen (e.g. `0.9 R`), which is strong evidence for the
  *result* even when the exact exit tick is not recoverable.

## Reading the frames

- The timeframe is read off the frame's own window title / top-left ticker
  (`UsaInd,M1`, `Ger40,M5`) — never assumed from the video's style. A wrong
  timeframe is the single most common silent error in the corpus.
- Extract the exact frame with the bundled scripts; read it multimodally, never
  OCR it and never reconstruct it from memory of similar charts.
- One or two essential frames per case (`entry_frame.jpg`, `exit_frame.jpg`),
  not a per-second sweep. Keep the short provenance clip in `clips/`.

## Finding entry/exit in the transcript

`yt-dlp` Hungarian auto-captions are the primary record. Use
`srt_tool.py search` with the words a trader actually uses — `beszállás`,
`beszállok`, `nyitva`, `jang`, `jin`, `pipa`, `kitörés`, `nyakvonal`,
`zárom`, `zártam`, `stop`, `kiléptem` — then `srt_tool.py window` around each
hit to read the surrounding context. The timestamps narrow where to look in the
video; the frame then confirms the exact price and moment. Machine ASR has
mis-transcriptions ("nyángszínál" for "jang szignál"); read in context against
the audio's evident intent rather than trusting a single word.

## Symbol resolution

`mt5_fetch.py list --match <hint>` to see the terminal's spellings, then pull
the candidate's price range and confirm it **overlaps the frame's own visible
price axis**. Lookup is case-sensitive and suffixes count (`EURUSD.a`,
`#GER40_U26`). `symbols_get()` enumerates names `symbol_select` may then refuse,
so enumeration is not proof a symbol is usable — a successful pull is.

## `copy_rates_range` quirk

It can return empty for a narrow window even when the data exists.
`mt5_fetch.py pull` already handles this (it widens to whole days and filters);
if you call MT5 yourself, do the same rather than believing the empty result.

## Classification

Classify explicitly: **JIN** (counter-trend line break + follow-through),
**JANG** (JIN plus a reversal pattern reaching its neckline), or a named
non-JIN/JANG technique (S/R zone retest, confluence-zone retest, Fibonacci
retest, Pipa szignál, Visszapattanás, Kitörés, trend-continuation breakdown,
…). Never rubber-stamp JIN/JANG onto a setup that does not narrate a
counter-trend line break; a continuation breakdown out of a consolidation is
not JIN/JANG no matter how clean it looks.

## Verify by rendering

A build is not done until `chart.html` has been rendered to PNG and visually
diffed against the source frame: entry/exit price and time, SL, level/zone
placement, and direction must all match. Data-level checks (OHLC matches, R
math) do not catch a chart that is numerically right but does not resemble the
source. `render_chart.py --png` does this.

## Scale and queue discipline

Process the channel's full census in strict reverse-chronological order (newest
first), no title pre-filtering — a title alone does not tell you whether a
video has a dateable trade. A video with no dateable trade still gets a row:
`no trade — skipped` with a one-line reason, never a silent omission. Scanning
all ~468 videos is the goal on the stronger device; each case is independent,
so progress is never lost by stopping partway.
