"""
CLI entry point for lrc-sync.

Usage:
    python cli.py --audio song.mp3 --lyrics lyrics.txt --output song.lrc
    python cli.py --audio song.mp3 --lyrics lyrics.txt --offset 0.5
    python cli.py --youtube "https://youtube.com/watch?v=..." --lyrics lyrics.txt
"""

import argparse
import sys
import tempfile
from pathlib import Path

from aligner import align, _build_initial_prompt, words_to_json
from logger import log
from downloader import download_audio


def _save_text(path, text, label):
    Path(path).write_text(text, encoding="utf-8")
    log("INFO", f"{label} written to {path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Sync lyrics with audio to create LRC files."
    )
    add = parser.add_argument
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--audio", "-a", help="Path to audio file (mp3, wav, flac, m4a)"
    )
    input_group.add_argument(
        "--youtube", "-y", help="YouTube URL to download audio from"
    )
    add(
        "--lyrics", "-l", required=True, help="Path to lyrics text file"
    )
    add(
        "--output", "-o", help="Output LRC file path (default: stdout)"
    )
    add(
        "--output-words", help="Output word-level timestamps JSON file path"
    )
    add(
        "--output-sync", help="Output character-level sync JSON file path (default: output_sync.json next to --output)"
    )
    add(
        "--characterlevel", action="store_true",
        help="Enable word/character-level JSON outputs (words.json, output_sync.json)"
    )
    add(
        "--model", "-m", default="medium",
        choices=["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo",
                 "tiny.en", "base.en", "small.en", "medium.en"],
        help="Whisper model size (default: medium; .en = English-only, poor on "
             "other languages). Larger is slower but more accurate, especially "
             "on CJK."
    )
    add(
        "--language", help="Language code (e.g., 'en', 'zh'). Auto-detect if omitted."
    )
    add(
        "--offset", type=float, default=0.0,
        help="Time offset in seconds (positive = lyrics appear later)"
    )
    add("--temperature", type=float, default=0.0,
                        help="Whisper sampling temperature (default 0.0)")
    add("--separate-vocals", action="store_true",
                        help="Separate vocals with Demucs before transcribing (requires demucs)")
    add("--initial-prompt", action="store_true",
                        help="Bias Whisper with the lyrics as decoder prompt (off by default; hurts small models)")
    add("--beam-size", type=int, default=5,
                        help="Whisper beam size (default 5; higher is slower "
                             "and measured no better on Japanese)")
    add("--best-of", type=int, default=5,
                        help="Whisper best_of (default 5)")
    add(
        "--similarity", default="bigram",
        choices=["bigram", "sets", "both"],
        help="Line/word matching score (default: bigram). 'sets' is the older "
             "order-insensitive bag-of-characters score; 'bigram' is "
             "order-sensitive and much better on CJK."
    )
    add("--accept-threshold", type=float, default=0.4,
                        help="Minimum match score to accept a line (default 0.4). "
                             "Below this the line is placed by interpolation.")
    add("--no-interpolate", action="store_true",
                        help="Disable interpolated placement of unmatched lines "
                             "(they fall back to previous-line + 1s)")
    add(
        "--publish", action="store_true",
        help="Publish the resulting LRC to LRCLIB (requires --track, --artist, --duration)"
    )
    add("--track", help="Track name for LRCLIB publish")
    add("--artist", help="Artist name for LRCLIB publish")
    add(
        "--duration", type=float,
        help="Track duration in seconds for LRCLIB publish"
    )
    add("--album", help="Album name for LRCLIB publish (optional)")
    add(
        "--method", default="stable-ts",
        choices=["stable-ts", "whisper"],
        help="Alignment backend (default: stable-ts).",
    )
 
    args = parser.parse_args()

    # Validate lyrics file
    if not Path(args.lyrics).exists():
        log("ERROR", f"Lyrics file not found: {args.lyrics}", file=sys.stderr)
        sys.exit(1)

    # Read lyrics
    lyrics_text = Path(args.lyrics).read_text(encoding="utf-8")

    # Get audio: download from YouTube or use local file
    temp_audio = None
    if args.youtube:
        log("INFO", "Downloading audio from YouTube...", file=sys.stderr)
        temp_audio = download_audio(args.youtube)
        audio_path = temp_audio
        log("INFO", f"Downloaded to {audio_path}", file=sys.stderr)
    else:
        if not Path(args.audio).exists():
            log("ERROR", f"Audio file not found: {args.audio}", file=sys.stderr)
            sys.exit(1)
        audio_path = args.audio

    try:
        # Run alignment
        log("INFO", f"Aligning audio with {args.lyrics}...", file=sys.stderr)

        def _progress(stage, _percent, message):
            log("INFO", f"[{stage}] {message}", file=sys.stderr)

        result = align(
            audio_path=audio_path,
            lyrics_text=lyrics_text,
            model_size=args.model,
            language=args.language,
            offset=args.offset,
            progress_callback=_progress,
            temperature=args.temperature,
            beam_size=args.beam_size,
            best_of=args.best_of,
            separate_vocals=args.separate_vocals,
            initial_prompt=_build_initial_prompt(lyrics_text) if args.initial_prompt else None,
            similarity_mode=args.similarity,
            accept_threshold=args.accept_threshold,
            interpolate_fallback=not args.no_interpolate,
            method=args.method,
        )

        # Print warnings
        for w in result.warnings:
            log("WARN", w, file=sys.stderr)

        # Output
        if args.output:
            _save_text(args.output, result.lrc_text, "LRC")
        else:
            print(result.lrc_text)

        if args.output_words:
            _save_text(args.output_words, words_to_json(result.words), "Words JSON")

        if args.output_sync:
            sync_out_path = Path(args.output_sync)
        elif args.output:
            sync_out_path = Path(args.output).with_name("output_sync.json")
        else:
            sync_out_path = Path("output_sync.json")
        if result.sync_text:
            _save_text(sync_out_path, result.sync_text, "Character sync JSON")

        # Publish to LRCLIB
        if args.publish:
            if not args.track or not args.artist or not args.duration:
                log("ERROR", "--publish requires --track, --artist, and --duration", file=sys.stderr)
                sys.exit(1)
            from lrclib import publish_lrc
            log("INFO", "Publishing to LRCLIB...", file=sys.stderr)
            publish_lrc(
                track_name=args.track,
                artist_name=args.artist,
                duration=args.duration,
                lrc_text=result.lrc_text,
                album_name=args.album,
            )
            log("INFO", "Published to LRCLIB.", file=sys.stderr)
    finally:
        # Clean up temp file
        if temp_audio and Path(temp_audio).exists():
            Path(temp_audio).unlink()


if __name__ == "__main__":
    main()
