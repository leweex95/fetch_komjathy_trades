#!/usr/bin/env python3
"""yt-dlp + ffmpeg wrapper for video-trade-ground-truth builds.

Standalone: depends only on the `yt-dlp` and `ffmpeg` executables being on
PATH (override with the YT_DLP / FFMPEG environment variables). It does not
import anything from this repository, so it can be copied into its own public
repo and run on another machine.

Why a wrapper exists at all: the original corpus was built by an agent
hand-typing yt-dlp/ffmpeg invocations for every video, which is where the
repeated effort and the inconsistencies came from. These subcommands are the
exact operations that were repeated, captured once.

Subcommands
-----------
  probe URL                 metadata + available subtitles for one video
  census CHANNEL_URL        id|duration|title TSV for a whole channel (newest first)
  subs URL -o DIR           Hungarian auto-caption transcript -> transcript.hu.srt
  clip URL --start T --end T -o F   download just a section (provenance clip)
  frame CLIP --at SECONDS -o F      extract one full-resolution frame from a clip

Times accept SS, MM:SS, or HH:MM:SS.

Bot checks: if YouTube answers with "Sign in to confirm you're not a bot",
pass `--cookies-from-browser BROWSER` (e.g. chrome, firefox, edge). This is the
single most common reason a fresh device's first fetch fails; it is a network
condition, not a script bug.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

YT_DLP = os.environ.get("YT_DLP", "yt-dlp")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")


def _run(cmd: list[str], *, capture: bool = False) -> str:
    printable = " ".join(cmd)
    print(f"+ {printable}", file=sys.stderr)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        sys.exit(f"ERROR: executable not found: {exc.filename!r}. Is it on PATH?")
    if proc.returncode != 0:
        if capture and proc.stderr:
            sys.stderr.write(proc.stderr)
        sys.exit(f"ERROR: command failed ({proc.returncode}): {printable}")
    return (proc.stdout or "") if capture else ""


def _parse_time(value: str) -> int:
    """SS, MM:SS, or HH:MM:SS -> whole seconds."""
    parts = value.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        sys.exit(f"ERROR: bad time value {value!r}; use SS, MM:SS or HH:MM:SS")
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    sys.exit(f"ERROR: bad time value {value!r}")


def _fmt_time(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _common(args: argparse.Namespace) -> list[str]:
    """Flags shared by every subcommand.

    `--extra-ydlp-arg` exists as an escape hatch: yt-dlp's anti-bot surface
    changes over time (PO tokens, JS runtimes, player clients), and a fresh
    device may need one flag this wrapper never anticipated. Passing it
    through beats editing this file on the target machine.
    """
    out: list[str] = []
    if getattr(args, "cookies_from_browser", None):
        out += ["--cookies-from-browser", args.cookies_from_browser]
    for extra in getattr(args, "extra_ydlp_arg", None) or []:
        out.append(extra)
    return out


def cmd_probe(args: argparse.Namespace) -> None:
    cmd = [YT_DLP, "-J", "--no-warnings", *_common(args), args.url]
    data = json.loads(_run(cmd, capture=True))
    subs = (data.get("subtitles") or {})
    autos = (data.get("automatic_captions") or {})
    info = {
        "id": data.get("id"),
        "title": data.get("title"),
        "upload_date": data.get("upload_date"),
        "duration": data.get("duration"),
        "uploader": data.get("uploader"),
        "webpage_url": data.get("webpage_url"),
        "manual_sub_langs": sorted(subs.keys()),
        "auto_caption_langs": sorted(autos.keys()),
        "has_hungarian_auto": any(k == "hu" or k.startswith("hu-") for k in autos),
    }
    text = json.dumps(info, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    print(text)


def cmd_census(args: argparse.Namespace) -> None:
    # --flat-playlist avoids fetching each video, so this is fast even for a
    # multi-hundred-video channel. -J returns one JSON object for the playlist.
    cmd = [YT_DLP, "--flat-playlist", "-J", "--no-warnings", *_common(args), args.channel_url]
    data = json.loads(_run(cmd, capture=True))
    entries = data.get("entries") or []
    rows = []
    for e in entries:
        if not e:
            continue
        dur = e.get("duration")
        rows.append((e.get("id", ""), int(dur) if dur else 0, (e.get("title") or "").replace("\t", " ")))
    if args.oldest_first:
        rows = list(reversed(rows))
    lines = [f"{vid}\t{dur}\t{title}" for vid, dur, title in rows]
    text = "\n".join(lines) + "\n"
    target = args.out or "CHANNEL_CENSUS.tsv"
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {target} ({len(lines)} videos, {'oldest' if args.oldest_first else 'newest'}-first)")


def cmd_subs(args: argparse.Namespace) -> None:
    os.makedirs(args.out, exist_ok=True)
    base = os.path.join(args.out, "transcript")
    cmd = [
        YT_DLP,
        "--skip-download",
        "--write-auto-sub",
        "--write-sub",
        "--sub-langs", args.lang,
        "--convert-subs", "srt",
        "--no-warnings",
        *_common(args),
        "-o", base,
        args.url,
    ]
    _run(cmd)
    produced = [f for f in os.listdir(args.out) if f.startswith("transcript") and f.endswith(".srt")]
    if not produced:
        sys.exit(
            "ERROR: no subtitle file was produced. This video may have no "
            "captions at all (record it as such rather than inventing one) -- "
            f"check with: {YT_DLP} --list-subs {args.url}"
        )
    print(f"wrote {os.path.join(args.out, produced[0])}")


def cmd_clip(args: argparse.Namespace) -> None:
    start, end = _parse_time(args.start), _parse_time(args.end)
    if end <= start:
        sys.exit("ERROR: --end must be after --start")
    fmt = "bv*" if args.video_only else "bv*+ba/b"
    if not os.path.splitext(args.out)[1]:
        sys.exit("ERROR: -o must include a file extension (e.g. clips/entry.mp4)")
    cmd = [
        YT_DLP,
        "-f", fmt,
        "--download-sections", f"*{_fmt_time(start)}-{_fmt_time(end)}",
        "--force-keyframes-at-cuts",
        "--no-warnings",
        *_common(args),
        "-o", args.out,
        args.url,
    ]
    if not args.video_only:
        cmd += ["--merge-output-format", "mp4"]
    _run(cmd)
    print(f"wrote {args.out} (video-time {_fmt_time(start)}-{_fmt_time(end)})")


def cmd_frame(args: argparse.Namespace) -> None:
    at = _parse_time(args.at)
    ext = ".png" if args.png else ".jpg"
    if not args.out.lower().endswith(ext):
        args.out = os.path.splitext(args.out)[0] + ext
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    # Full source resolution, no scaling: the frame IS the evidence, so
    # downscaling here would destroy exactly the detail an entry price or a
    # timeframe label is read from. -ss before -i is the fast seek; modern
    # ffmpeg still lands on the requested frame.
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", str(at), "-i", args.clip, "-frames:v", "1"]
    cmd += ([ "-compression_level", "6" ] if args.png else ["-q:v", str(args.quality)])
    cmd.append(args.out)
    _run(cmd)
    print(f"wrote {args.out} (clip-time {_fmt_time(at)})")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--cookies-from-browser", metavar="BROWSER",
                        help="pass through to yt-dlp when YouTube demands a bot check")
        sp.add_argument("--extra-ydlp-arg", action="append", metavar="ARG",
                        help="escape hatch: pass one extra argument straight to yt-dlp (repeatable)")

    sp = sub.add_parser("probe", help="metadata + available subtitles for one video")
    sp.add_argument("url")
    sp.add_argument("--out", help="write the metadata JSON here")
    add_common(sp)
    sp.set_defaults(func=cmd_probe)

    sp = sub.add_parser("census", help="id|duration|title TSV for a whole channel")
    sp.add_argument("channel_url", help="e.g. https://www.youtube.com/@KA-FXTanoda/videos")
    sp.add_argument("--out", default="CHANNEL_CENSUS.tsv")
    sp.add_argument("--oldest-first", action="store_true")
    add_common(sp)
    sp.set_defaults(func=cmd_census)

    sp = sub.add_parser("subs", help="download auto-captions as transcript.hu.srt")
    sp.add_argument("url")
    sp.add_argument("-o", "--out", required=True, help="output directory")
    sp.add_argument("--lang", default="hu")
    add_common(sp)
    sp.set_defaults(func=cmd_subs)

    sp = sub.add_parser("clip", help="download one short section (provenance clip)")
    sp.add_argument("url")
    sp.add_argument("--start", required=True)
    sp.add_argument("--end", required=True)
    sp.add_argument("-o", "--out", required=True)
    sp.add_argument("--video-only", action="store_true",
                    help="best video only, no audio (smaller; enough for frames)")
    add_common(sp)
    sp.set_defaults(func=cmd_clip)

    sp = sub.add_parser("frame", help="extract one full-resolution frame from a clip")
    sp.add_argument("clip")
    sp.add_argument("--at", required=True, help="timestamp WITHIN the clip")
    sp.add_argument("-o", "--out", required=True)
    sp.add_argument("--png", action="store_true", help="lossless PNG instead of JPEG")
    sp.add_argument("--quality", type=int, default=2, help="JPEG q:v (2=high, 31=low)")
    sp.set_defaults(func=cmd_frame)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
