#!/usr/bin/env python3
"""Parse and search an SRT transcript. Standalone, stdlib only.

This is the deterministic half of "find the trade in the video": the model
still decides which cue marks the entry, but it should not be scanning a raw
caption file by eye. `search` greps the cues for the words a trader actually
says (beszállás, jang, nyitva, zárom, stop, ...) and prints their timestamps;
`window` shows everything said around a moment; `to-txt` produces the
deduplicated plain text the corpus keeps as transcript_clean.txt.

Cue times accept SS, MM:SS, or HH:MM:SS.
"""
from __future__ import annotations

import argparse
import re
import sys

_TS_RE = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})"
)
_TAG_RE = re.compile(r"<[^>]+>")


def _sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def fmt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_precise(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def parse_time(value: str) -> float:
    parts = value.strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        sys.exit(f"ERROR: bad time value {value!r}; use SS, MM:SS or HH:MM:SS")
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    sys.exit(f"ERROR: bad time value {value!r}")


def parse_srt(path: str) -> list[tuple[float, float, str]]:
    """Tolerant SRT/VTT reader -> [(start_sec, end_sec, text), ...].

    Deliberately tolerant because the inputs vary: youtube auto-captions arrive
    as .vtt that was converted to .srt, sometimes with `WEBVTT` headers, cue
    numbers, inline `<c>`/`<00:00:00.000>` tags, BOMs and CRLF all mixed.
    A strict grammar would reject files that are perfectly usable.
    """
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        raw = fh.read()
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[tuple[float, float, str]] = []
    # Split on blank lines; each block is [index?] time-line + text lines.
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        ts_idx = None
        m = None
        for i, ln in enumerate(lines):
            m2 = _TS_RE.search(ln)
            if m2 and "-->" in ln:
                ts_idx, m = i, m2
                break
        if ts_idx is None or m is None:
            continue
        times = _TS_RE.findall(lines[ts_idx])
        if len(times) < 2:
            continue
        start = _sec(*times[0])
        end = _sec(*times[1])
        body = " ".join(_TAG_RE.sub("", ln) for ln in lines[ts_idx + 1:]).strip()
        cues.append((start, end, body))
    cues.sort(key=lambda c: c[0])
    return cues


def _dedupe(cues: list[tuple[float, float, str]]) -> str:
    """Auto-captions emit the same rolling line many times; collapse runs of
    identical text so the plain-text version reads like speech, not a stutter."""
    out: list[str] = []
    for _s, _e, body in cues:
        if not body:
            continue
        if out and (body == out[-1] or (out[-1] and body.startswith(out[-1]))):
            if len(body) > len(out[-1]):
                out[-1] = body
            continue
        out.append(body)
    return "\n".join(out)


def cmd_timestamps(args: argparse.Namespace) -> None:
    cues = parse_srt(args.srt)
    lines = [f"{fmt_precise(s)}\t{fmt_precise(e)}\t{body}" for s, e, body in cues]
    text = "\n".join(lines) + ("\n" if lines else "")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out} ({len(lines)} cues)", file=sys.stderr)
    else:
        sys.stdout.write(text)


def cmd_to_txt(args: argparse.Namespace) -> None:
    text = _dedupe(parse_srt(args.srt)) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(text)


def cmd_search(args: argparse.Namespace) -> None:
    cues = parse_srt(args.srt)
    terms = [t.strip().lower() for t in args.terms.split(",") if t.strip()]
    if not terms:
        sys.exit("ERROR: --terms is empty")
    hits = [i for i, (_s, _e, body) in enumerate(cues) if any(t in body.lower() for t in terms)]
    if not hits:
        print(f"no cues matched {terms}", file=sys.stderr)
        return
    printed: set[int] = set()
    for i in hits:
        lo, hi = max(0, i - args.context), min(len(cues) - 1, i + args.context)
        for j in range(lo, hi + 1):
            if j in printed:
                continue
            printed.add(j)
            s, e, body = cues[j]
            mark = "*" if j in hits else " "
            print(f"{mark} [{fmt(s)}-{fmt(e)}] {body}")


def cmd_window(args: argparse.Namespace) -> None:
    cues = parse_srt(args.srt)
    lo, hi = parse_time(args.start), parse_time(args.end)
    for s, e, body in cues:
        if e >= lo and s <= hi:
            print(f"[{fmt(s)}-{fmt(e)}] {body}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("timestamps", help="every cue as start<TAB>end<TAB>text")
    sp.add_argument("srt")
    sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_timestamps)

    sp = sub.add_parser("to-txt", help="deduplicated plain text (transcript_clean.txt)")
    sp.add_argument("srt")
    sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_to_txt)

    sp = sub.add_parser("search", help="find cues containing any of these comma-separated terms")
    sp.add_argument("srt")
    sp.add_argument("--terms", required=True,
                    help="e.g. 'beszállás,jang,nyitva,zárom,stop,kilépés'")
    sp.add_argument("--context", type=int, default=0, help="extra cues shown around each hit")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("window", help="print every cue overlapping a time window")
    sp.add_argument("srt")
    sp.add_argument("--start", required=True)
    sp.add_argument("--end", required=True)
    sp.set_defaults(func=cmd_window)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
