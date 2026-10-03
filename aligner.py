"""
Core alignment pipeline: audio + lyrics → synced LRC file.
"""

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class WordTimestamp:
    """A single word with its start and end time."""
    word: str
    start: float
    end: float


@dataclass
class LineTimestamp:
    """A lyric line with its start time."""
    line: str
    start: float


@dataclass
class AlignmentResult:
    """Result of the alignment pipeline."""
    lines: list[LineTimestamp] = field(default_factory=list)
    lrc_text: str = ""
    warnings: list[str] = field(default_factory=list)


def _find_ffmpeg() -> Optional[str]:
    """Find ffmpeg executable. Returns path or None."""
    import shutil
    # Check PATH first
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    # Check local project directory
    project_dir = Path(__file__).parent
    for pattern in ["ffmpeg-*/bin/ffmpeg.exe", "ffmpeg-*/bin/ffmpeg"]:
        matches = list(project_dir.glob(pattern))
        if matches:
            return str(matches[0])

    return None


def convert_to_wav(audio_path: str, output_path: Optional[str] = None) -> str:
    """Convert any audio format to 16kHz mono WAV using ffmpeg."""
    if output_path is None:
        output_path = tempfile.mktemp(suffix=".wav")

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found. Please install ffmpeg or place it in the project directory.")

    cmd = [
        ffmpeg, "-y", "-i", audio_path,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")
    return output_path


def transcribe_with_whisper(
    wav_path: str,
    model_size: str = "small",
    language: Optional[str] = None,
    progress_callback=None,
) -> list[WordTimestamp]:
    """Run faster-whisper with word-level timestamps."""
    from faster_whisper import WhisperModel

    if progress_callback:
        progress_callback("loading_model", 0, "Loading Whisper model (downloads on first run)...")

    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    if progress_callback:
        progress_callback("transcribing", 0, "Transcribing...")

    segments, info = model.transcribe(
        wav_path,
        word_timestamps=True,
        language=language,
        # NOTE: vad_filter must stay OFF for sung music. Silero VAD
        # classifies sung vocals over instruments as non-speech and
        # discards ~90% of the song (verified: 14 words with VAD vs
        # 236 words without, on the same track).
        vad_filter=False,
    )

    words: list[WordTimestamp] = []
    total_duration = info.duration if hasattr(info, 'duration') else 0

    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append(WordTimestamp(
                    word=w.word.strip(),
                    start=w.start,
                    end=w.end,
                ))
        if progress_callback and total_duration > 0:
            pct = min(100, int((segment.end / total_duration) * 100))
            progress_callback("transcribing", pct, f"Transcribing... {pct}%")

    if progress_callback:
        progress_callback("transcribing", 100, "Transcription complete")

    return words


def _normalize(text: str) -> str:
    """Normalize text for fuzzy matching: lowercase, strip punctuation."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _contains_cjk(text: str) -> bool:
    """Check if text contains CJK characters (Chinese, Japanese, Korean)."""
    for ch in text:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF or  # hiragana + katakana
                0x31F0 <= o <= 0x31FF or  # katakana phonetic extensions
                0x3400 <= o <= 0x4DBF or  # CJK extension A
                0x4E00 <= o <= 0x9FFF or  # CJK unified ideographs
                0xAC00 <= o <= 0xD7AF):  # hangul syllables
            return True
    return False


def match_lyrics_to_words(
    lyrics: list[str],
    words: list[WordTimestamp],
) -> tuple[list[LineTimestamp], list[str]]:
    """
    Fuzzy-match lyric lines against Whisper word timestamps.
    Returns line-level timestamps and any warnings.
    """
    warnings: list[str] = []
    result: list[LineTimestamp] = []

    # Normalize whisper words
    norm_words = [(w, _normalize(w.word)) for w in words]
    # Filter out empty normalized words
    norm_words = [(w, nw) for w, nw in norm_words if nw]

    word_idx = 0
    total_words = len(norm_words)

    for line in lyrics:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        norm_line = _normalize(line_stripped)
        if not norm_line:
            continue

        # Try to find the best matching window of words
        best_start = None
        best_score = 0.0
        best_end_idx = word_idx

        # Estimate how many whisper words a line spans.
        # CJK text has no spaces, so estimate from character count instead.
        if _contains_cjk(norm_line):
            est_words = max(2, len(norm_line.replace(" ", "")) // 2)
        else:
            est_words = len(norm_line.split())

        # Search through remaining words
        search_start = max(0, word_idx - 5)  # allow some backtracking
        search_end = min(total_words, word_idx + est_words * 3 + 10)

        for i in range(search_start, search_end):
            # Build a candidate phrase from consecutive words
            candidate_words = []
            candidate_text = ""
            for j in range(i, min(i + est_words + 5, total_words)):
                candidate_words.append(norm_words[j][1])
                candidate_text = " ".join(candidate_words)

                # Calculate similarity
                score = _similarity(norm_line, candidate_text)
                if score > best_score:
                    best_score = score
                    best_start = norm_words[i][0].start
                    best_end_idx = j

        if best_start is not None and best_score > 0.3:
            # Enforce monotonic timestamps: never go back in time.
            # A match earlier than the previous line is spurious (e.g. a
            # repeated chorus fragment) — fall back instead.
            if result and best_start < result[-1].start:
                warnings.append(f"Could not match line: '{line_stripped}'")
                result.append(LineTimestamp(
                    line=line_stripped,
                    start=result[-1].start + 1.0
                ))
            else:
                result.append(LineTimestamp(line=line_stripped, start=best_start))
                # Advance word index past the matched region
                word_idx = best_end_idx + 1
        else:
            warnings.append(f"Could not match line: '{line_stripped}'")
            # Use previous line's start + 1s as fallback
            if result:
                result.append(LineTimestamp(
                    line=line_stripped,
                    start=result[-1].start + 1.0
                ))
            else:
                result.append(LineTimestamp(line=line_stripped, start=0.0))

    return result, warnings


def _similarity(a: str, b: str) -> float:
    """Word-overlap similarity, falling back to character-level for CJK text."""
    if _contains_cjk(a) or _contains_cjk(b):
        a_chars = set(a.replace(" ", ""))
        b_chars = set(b.replace(" ", ""))
        if not a_chars or not b_chars:
            return 0.0
        overlap = a_chars & b_chars
        return len(overlap) / max(len(a_chars), len(b_chars))
    a_words = set(a.split())
    b_words = set(b.split())
    if not a_words or not b_words:
        return 0.0
    overlap = a_words & b_words
    return len(overlap) / max(len(a_words), len(b_words))


def format_lrc(
    lines: list[LineTimestamp],
    offset: float = 0.0,
    merge_consecutive: bool = True,
) -> str:
    """Format line-level timestamps as LRC text."""
    if not lines:
        return ""

    # Apply offset
    adjusted = []
    for lt in lines:
        start = max(0.0, lt.start + offset)
        adjusted.append(LineTimestamp(line=lt.line, start=start))

    # Merge consecutive lines with same timestamp
    if merge_consecutive:
        merged: list[LineTimestamp] = []
        for lt in adjusted:
            if merged and abs(merged[-1].start - lt.start) < 0.01:
                merged[-1] = LineTimestamp(
                    line=merged[-1].line + " / " + lt.line,
                    start=lt.start
                )
            else:
                merged.append(lt)
        adjusted = merged

    # Format as LRC
    lrc_lines = []
    for lt in adjusted:
        minutes = int(lt.start // 60)
        seconds = lt.start % 60
        lrc_lines.append(f"[{minutes:02d}:{seconds:05.2f}]{lt.line}")

    return "\n".join(lrc_lines) + "\n"


def align(
    audio_path: str,
    lyrics_text: str,
    model_size: str = "small",
    language: Optional[str] = None,
    offset: float = 0.0,
    progress_callback=None,
) -> AlignmentResult:
    """
    Full alignment pipeline: audio + lyrics → LRC.

    Args:
        audio_path: Path to audio file (mp3, wav, flac, m4a, etc.)
        lyrics_text: Lyrics as plain text (one line per lyric line)
        model_size: Whisper model size (tiny, base, small, medium, large-v3)
        language: Language code (e.g., 'en', 'zh') or None for auto-detect
        offset: Time offset in seconds (positive = lyrics appear later)
        progress_callback: Optional callback(stage, percent, message).
            Stages: converting → loading_model → transcribing → matching → done

    Returns:
        AlignmentResult with lines, LRC text, and warnings
    """
    result = AlignmentResult()

    # Parse lyrics
    lyrics_lines = [l for l in lyrics_text.split("\n") if l.strip()]
    if not lyrics_lines:
        result.warnings.append("No lyrics provided")
        return result

    # Convert audio to WAV
    if progress_callback:
        progress_callback("converting", 0, "Converting audio...")
    wav_path = convert_to_wav(audio_path)
    if progress_callback:
        progress_callback("converting", 100, "Audio converted")

    try:
        # Transcribe with Whisper
        words = transcribe_with_whisper(
            wav_path, model_size, language, progress_callback=progress_callback
        )

        if not words:
            result.warnings.append("Whisper returned no word timestamps")
            return result

        # Match lyrics to words
        if progress_callback:
            progress_callback("matching", 0, "Matching lyrics...")
        line_timestamps, warnings = match_lyrics_to_words(lyrics_lines, words)
        result.warnings.extend(warnings)
        result.lines = line_timestamps

        # Format as LRC
        result.lrc_text = format_lrc(line_timestamps, offset=offset)

        if progress_callback:
            progress_callback("done", 100, "Done!")

    finally:
        # Clean up temp WAV
        if os.path.exists(wav_path):
            os.remove(wav_path)

    return result
