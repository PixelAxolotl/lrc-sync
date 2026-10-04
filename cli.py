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

from aligner import align
from downloader import download_audio


def main():
    parser = argparse.ArgumentParser(
        description="Sync lyrics with audio to create LRC files."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--audio", "-a", help="Path to audio file (mp3, wav, flac, m4a)"
    )
    input_group.add_argument(
        "--youtube", "-y", help="YouTube URL to download audio from"
    )
    parser.add_argument(
        "--lyrics", "-l", required=True, help="Path to lyrics text file"
    )
    parser.add_argument(
        "--output", "-o", help="Output LRC file path (default: stdout)"
    )
    parser.add_argument(
        "--output-words", help="Output word-level timestamps JSON file path"
    )
    parser.add_argument(
        "--output-sync", help="Output per-character sync JSON file path (requires --characterlevel)"
    )
    parser.add_argument(
        "--characterlevel", action="store_true",
        help="Enable word/character-level JSON outputs (words.json, output_sync.json)"
    )
    parser.add_argument(
        "--model", "-m", default="small",
        choices=["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
        help="Whisper model size (default: small)"
    )
    parser.add_argument(
        "--language", help="Language code (e.g., 'en', 'zh'). Auto-detect if omitted."
    )
    parser.add_argument(
        "--offset", type=float, default=0.0,
        help="Time offset in seconds (positive = lyrics appear later)"
    )
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="Whisper sampling temperature (default 0.0)")
    parser.add_argument("--beam-size", type=int, default=5,
                        help="Whisper beam size (default 5)")
    parser.add_argument("--best-of", type=int, default=5,
                        help="Whisper best_of (default 5)")
    parser.add_argument(
        "--publish", action="store_true",
        help="Publish the resulting LRC to LRCLIB (requires --track, --artist, --duration)"
    )
    parser.add_argument("--track", help="Track name for LRCLIB publish")
    parser.add_argument("--artist", help="Artist name for LRCLIB publish")
    parser.add_argument(
        "--duration", type=float,
        help="Track duration in seconds for LRCLIB publish"
    )
    parser.add_argument("--album", help="Album name for LRCLIB publish (optional)")

    args = parser.parse_args()

    if (args.output_words or args.output_sync) and not args.characterlevel:
        print(
            "Error: --output-words/--output-sync require --characterlevel",
            file=sys.stderr,
        )
        sys.exit(2)

    # Validate lyrics file
    if not Path(args.lyrics).exists():
        print(f"Error: Lyrics file not found: {args.lyrics}", file=sys.stderr)
        sys.exit(1)

    # Read lyrics
    lyrics_text = Path(args.lyrics).read_text(encoding="utf-8")

    # Get audio: download from YouTube or use local file
    temp_audio = None
    if args.youtube:
        print(f"Downloading audio from YouTube...", file=sys.stderr)
        temp_audio = download_audio(args.youtube)
        audio_path = temp_audio
        print(f"Downloaded to {audio_path}", file=sys.stderr)
    else:
        if not Path(args.audio).exists():
            print(f"Error: Audio file not found: {args.audio}", file=sys.stderr)
            sys.exit(1)
        audio_path = args.audio

    try:
        # Run alignment
        print(f"Aligning audio with {args.lyrics}...", file=sys.stderr)

        def _progress(stage, percent, message):
            print(f"[{stage}] {message}", file=sys.stderr)

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
        )

        # Print warnings
        for w in result.warnings:
            print(f"Warning: {w}", file=sys.stderr)

        # Output
        if args.output:
            Path(args.output).write_text(result.lrc_text, encoding="utf-8")
            print(f"LRC written to {args.output}", file=sys.stderr)
        else:
            print(result.lrc_text)

        if args.output_words:
            from aligner import words_to_json
            Path(args.output_words).write_text(
                words_to_json(result.words), encoding="utf-8")
            print(f"Words JSON written to {args.output_words}", file=sys.stderr)

        if args.output_sync:
            Path(args.output_sync).write_text(result.sync_text, encoding="utf-8")
            print(f"Sync JSON written to {args.output_sync}", file=sys.stderr)

        # Publish to LRCLIB
        if args.publish:
            if not args.track or not args.artist or not args.duration:
                print(
                    "Error: --publish requires --track, --artist, and --duration",
                    file=sys.stderr,
                )
                sys.exit(1)
            from lrclib import publish_lrc
            print("Publishing to LRCLIB...", file=sys.stderr)
            publish_lrc(
                track_name=args.track,
                artist_name=args.artist,
                duration=args.duration,
                lrc_text=result.lrc_text,
                album_name=args.album,
            )
            print("Published to LRCLIB.", file=sys.stderr)
    finally:
        # Clean up temp file
        if temp_audio and Path(temp_audio).exists():
            Path(temp_audio).unlink()


if __name__ == "__main__":
    main()
