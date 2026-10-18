#!/usr/bin/env python3
"""Scaffold a video-ground-truth case folder and maintain the trade manifest.

Standalone, stdlib only.

Why this exists: the corpus's folder naming, its `case.json`/`notes.md`
skeleton, and the machine-readable list of "which trade happened when, on
which symbol" were all reproduced by hand for every video, and drifted. This
makes the layout and the manifest deterministic.

Folder convention (from the corpus):
    <INSTRUMENT>+<YYYY-MM-DD_HHMM>+<video-title-slug>/
        frames/  clips/  transcript.hu.srt  transcript_clean.txt
        mt5_ohlc_*.csv  build_chart.py  chart.html  notes.md  case.json

The manifest (<root>/TRADES_INDEX.tsv) is regenerated from every case.json,
so it can never drift from the individual cases.

`record` is the step that answers "save out the exact datetime ranges +
symbols where the trade happened": it writes the entry/exit times, prices,
instrument and broker symbol into case.json and refreshes the manifest.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

NOTES_TEMPLATE = """# {instrument} {direction} — {when}

Video: "{title}" — Komjáthy Attila. Video id `{video_id}`.
URL: {url}

## Look here first

- `chart.html` — real MT5 `{symbol}` {timeframe} candles, entry/exit marked.
- `frames/entry_frame.jpg` (video-time ~{entry_video_time}) — the entry moment.
- `frames/exit_frame.jpg` (video-time ~{exit_video_time}) — the exit moment.

## Entry

| | |
|---|---|
| Real time (broker) | **{entry_time}** |
| Price | **{entry_price}** |
| Direction | {direction} |
| Stop | {sl} |
| Timeframe | {timeframe} (read off the frame, never assumed) |

## Exit

| | |
|---|---|
| Real time (broker) | **{exit_time}** |
| Price | **{exit_price}** |
| R-multiple | {r} |

## Classification

<!-- JIN / JANG / a named non-JIN-JANG technique — whichever the transcript and
     chart actually support. Never rubber-stamp JIN/JANG. -->

## Symbol resolution

<!-- mt5_fetch.py list --match X; cross-check the frame's visible price axis
     against the fetched range before committing. -->

## Files

- `transcript.hu.srt`, `transcript_clean.txt`
- `clips/`, `frames/`
- `mt5_ohlc_*.csv`
- `chart.html`

## Still open

<!-- every reconstruction, every value that is REASONABLE_INTERPRETATION
     rather than SOURCE_CONFIRMED -->
"""


def slugify(text: str, max_len: int = 80) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def _case_json(folder: str) -> str:
    return os.path.join(folder, "case.json")


def cmd_new(args: argparse.Namespace) -> None:
    when = args.when.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[_ ](\d{2})(\d{2})$", when)
    if not m:
        sys.exit("ERROR: --when must look like YYYY-MM-DD_HHMM (real trade time, broker clock)")
    slug = args.slug or slugify(args.title or args.video_id)
    folder_name = f"{args.instrument.upper()}+{m.group(1)}_{m.group(2)}{m.group(3)}+{slug}"
    folder = os.path.join(args.root, folder_name)
    if os.path.exists(folder):
        sys.exit(f"ERROR: {folder} already exists")
    os.makedirs(os.path.join(folder, "frames"))
    os.makedirs(os.path.join(folder, "clips"))
    case = {
        "folder": folder_name,
        "video_id": args.video_id,
        "video_url": args.url or (f"https://www.youtube.com/watch?v={args.video_id}" if args.video_id else None),
        "video_title": args.title,
        "instrument": args.instrument.upper(),
        "broker_symbol": args.symbol,
        "timeframe": args.timeframe,
        "direction": None,
        "entry": {"time": None, "price": None, "video_time": None},
        "exit": {"time": None, "price": None, "video_time": None},
        "stop": None,
        "r_multiple": None,
        "classification": None,
        "artifacts": {"ohlc_csv": None, "entry_frame": None, "exit_frame": None},
        "provenance": {},   # label -> SOURCE_CONFIRMED | REASONABLE_INTERPRETATION | ...
    }
    with open(_case_json(folder), "w", encoding="utf-8") as fh:
        json.dump(case, fh, indent=2, ensure_ascii=False)
    notes = NOTES_TEMPLATE.format(
        instrument=args.instrument.upper(), direction="<long|short>", when=when,
        title=args.title or "", video_id=args.video_id, url=case["video_url"] or "",
        symbol=args.symbol or "<broker symbol>", timeframe=args.timeframe or "<timeframe>",
        entry_video_time="?", exit_video_time="?",
        entry_time="?", entry_price="?", sl="?", exit_time="?", exit_price="?", r="?",
    )
    with open(os.path.join(folder, "notes.md"), "w", encoding="utf-8") as fh:
        fh.write(notes)
    print(folder)


def cmd_record(args: argparse.Namespace) -> None:
    folder = args.case if os.path.isabs(args.case) else os.path.join(args.root, args.case)
    path = _case_json(folder)
    if not os.path.exists(path):
        sys.exit(f"ERROR: no case.json at {path}; run `new` first")
    with open(path, encoding="utf-8-sig") as fh:
        case = json.load(fh)
    if args.entry_time:
        case["entry"]["time"] = args.entry_time
    if args.entry_price is not None:
        case["entry"]["price"] = args.entry_price
    if args.entry_video_time:
        case["entry"]["video_time"] = args.entry_video_time
    if args.exit_time:
        case["exit"]["time"] = args.exit_time
    if args.exit_price is not None:
        case["exit"]["price"] = args.exit_price
    if args.exit_video_time:
        case["exit"]["video_time"] = args.exit_video_time
    if args.direction:
        case["direction"] = args.direction
    if args.symbol:
        case["broker_symbol"] = args.symbol
    if args.instrument:
        case["instrument"] = args.instrument.upper()
    if args.timeframe:
        case["timeframe"] = args.timeframe
    if args.sl is not None:
        case["stop"] = args.sl
    if args.r is not None:
        case["r_multiple"] = args.r
    if args.classification:
        case["classification"] = args.classification
    if args.ohlc_csv:
        case["artifacts"]["ohlc_csv"] = args.ohlc_csv
    if args.entry_frame:
        case["artifacts"]["entry_frame"] = args.entry_frame
    if args.exit_frame:
        case["artifacts"]["exit_frame"] = args.exit_frame
    for tag in args.tag or []:
        # --tag label=SOURCE_CONFIRMED
        if "=" not in tag:
            sys.exit(f"ERROR: --tag expects label=STATUS, got {tag!r}")
        label, status = tag.split("=", 1)
        case.setdefault("provenance", {})[label] = status
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(case, fh, indent=2, ensure_ascii=False)
    _write_index(args.root)
    print(f"recorded {case['folder']} (entry {case['entry']['time']} exit {case['exit']['time']} {case['instrument']})")


def _write_index(root: str) -> None:
    rows = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name, "case.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as fh:
            c = json.load(fh)
        rows.append([
            name, c.get("video_id") or "", c.get("instrument") or "", c.get("broker_symbol") or "",
            c.get("direction") or "", c.get("timeframe") or "",
            (c.get("entry") or {}).get("time") or "", str((c.get("entry") or {}).get("price") or ""),
            (c.get("exit") or {}).get("time") or "", str((c.get("exit") or {}).get("price") or ""),
            str(c.get("r_multiple") if c.get("r_multiple") is not None else ""),
            c.get("classification") or "",
        ])
    header = ["folder", "video_id", "instrument", "broker_symbol", "direction", "timeframe",
              "entry_time", "entry_price", "exit_time", "exit_price", "r_multiple", "classification"]
    out = os.path.join(root, "TRADES_INDEX.tsv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    return out


def cmd_index(args: argparse.Namespace) -> None:
    out = _write_index(args.root)
    with open(out, encoding="utf-8") as fh:
        sys.stdout.write(fh.read())
    print(f"# wrote {out}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("new", help="create a case folder with case.json + notes.md skeleton")
    sp.add_argument("--root", required=True, help="corpus root, e.g. research/video_ground_truth")
    sp.add_argument("--instrument", required=True)
    sp.add_argument("--when", required=True, help="real trade time YYYY-MM-DD_HHMM (broker clock)")
    sp.add_argument("--slug", help="title slug (default: derived from --title)")
    sp.add_argument("--title")
    sp.add_argument("--video-id", required=True)
    sp.add_argument("--url")
    sp.add_argument("--symbol", help="broker symbol, e.g. #US30")
    sp.add_argument("--timeframe", help="M1/M5/M15/... (from the frame)")
    sp.set_defaults(func=cmd_new)

    sp = sub.add_parser("record", help="write trade times/prices/symbol into case.json + refresh manifest")
    sp.add_argument("--root", required=True)
    sp.add_argument("--case", required=True, help="case folder name (or absolute path)")
    sp.add_argument("--entry-time"); sp.add_argument("--entry-price", type=float)
    sp.add_argument("--exit-time"); sp.add_argument("--exit-price", type=float)
    sp.add_argument("--entry-video-time"); sp.add_argument("--exit-video-time")
    sp.add_argument("--direction", choices=["long", "short"])
    sp.add_argument("--symbol"); sp.add_argument("--instrument"); sp.add_argument("--timeframe")
    sp.add_argument("--sl", type=float); sp.add_argument("--r", type=float)
    sp.add_argument("--classification")
    sp.add_argument("--ohlc-csv"); sp.add_argument("--entry-frame"); sp.add_argument("--exit-frame")
    sp.add_argument("--tag", action="append", metavar="LABEL=STATUS",
                    help="provenance tag, e.g. entry_price=SOURCE_CONFIRMED (repeatable)")
    sp.set_defaults(func=cmd_record)

    sp = sub.add_parser("index", help="regenerate TRADES_INDEX.tsv from all case.json files")
    sp.add_argument("--root", required=True)
    sp.set_defaults(func=cmd_index)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
