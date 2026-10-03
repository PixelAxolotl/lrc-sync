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
    words: list[WordTimestamp] = field(default_factory=list)
    spans: list = field(default_factory=list)
    sync_text: str = ""
    detected_language: Optional[str] = None


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


_tiny_model = None

def detect_language_from_text(text: str) -> Optional[str]:
    """Fast Unicode-script heuristic. Returns a language code only when the
    script maps uniquely (e.g. kana ⇒ ja, hangul ⇒ ko, thai ⇒ th).
    Returns None for scripts shared by several languages (latin, cyrillic,
    hanzi-only, arabic, devanagari) so the caller can fall back to the
    tiny audio model."""
    has_kana = False
    has_hangul = False
    has_thai = False
    has_ar = False
    has_dev = False
    has_hanzi = False
    has_cyrillic = False
    has_latin = False

    for ch in text:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF:
            has_kana = True
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            has_hangul = True
        elif 0x0E00 <= o <= 0x0E7F:
            has_thai = True
        elif 0x0600 <= o <= 0x06FF:
            has_ar = True
        elif 0x0900 <= o <= 0x097F:
            has_dev = True
        elif 0x4E00 <= o <= 0x9FFF:
            has_hanzi = True
        elif 0x0400 <= o <= 0x04FF:
            has_cyrillic = True
        elif ch.isascii() and ch.isalpha():
            has_latin = True

    # Unique scripts first
    if has_kana:
        return "ja"
    if has_hangul:
        return "ko"
    if has_thai:
        return "th"
    # Shared scripts: ambiguous, defer to the audio model
    if has_ar or has_dev or has_cyrillic or has_latin or has_hanzi:
        return None
    return None


def detect_language_tiny(wav_path: str) -> tuple[str, float]:
    """Detect audio language with a tiny CPU model (fast), for auto mode."""
    global _tiny_model
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    if _tiny_model is None:
        _tiny_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    audio = decode_audio(wav_path, sampling_rate=16000)
    language, probability, _ = _tiny_model.detect_language(audio)
    return language, probability


def transcribe_with_whisper(
    wav_path: str,
    model_size: str = "small",
    language: Optional[str] = None,
    progress_callback=None,
    temperature: float = 0.0,
    beam_size: int = 5,
    best_of: int = 5,
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
        temperature=temperature,
        beam_size=beam_size,
        best_of=best_of,
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
    return_spans: bool = False,
):
    """
    Fuzzy-match lyric lines against Whisper word timestamps.
    Returns line-level timestamps and any warnings. With return_spans=True,
    also returns a per-line span (start_idx, end_idx) into `words` or None.
    """
    warnings: list[str] = []
    result: list[LineTimestamp] = []
    spans: list = []

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
        best_i = None

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
                    best_i = i

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
                spans.append(None)
            else:
                result.append(LineTimestamp(line=line_stripped, start=best_start))
                # Advance word index past the matched region
                spans.append((best_i, best_end_idx) if best_i is not None else None)
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
            spans.append(None)

    if return_spans:
        fallback_count = sum(1 for s in spans if s is None)
    else:
        fallback_count = sum(
            1 for i, lt in enumerate(result)
            if i < len(warnings) and (
                "Could not match line" in warnings[i]))
    if result and fallback_count / len(result) > 0.25:
        warnings.append(
            f"Over 25% of lyric lines did not match the transcription "
            f"(fallback +1s timestamps used). Check the language/model settings."
        )
    if return_spans:
        return result, warnings, spans
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


def words_to_json(words: list[WordTimestamp], offset: float = 0.0) -> str:
    """Serialize word timestamps as JSON: {"words": [{word, start, end}]}."""
    import json

    return json.dumps({"words": [
        {
            "word": w.word,
            "start": round(max(0.0, w.start + offset), 3),
            "end": round(max(0.0, w.end + offset), 3),
        }
        for w in words
    ]})


def _norm_words_for_spans(words: list[WordTimestamp]) -> list[WordTimestamp]:
    return [(w) for w in words if _normalize(w.word)]


def sync_json(
    lines: list[LineTimestamp],
    lyric_lines: list[str],
    spans: list,
    words: list[WordTimestamp],
) -> str:
    """Per-character sync JSON: {"lines": [{"start", "end", "chars": [...]}]}.

    start/end are inclusive char indices of the line within the lyrics with
    newlines removed; chars holds one start time per character.
    """
    import json

    norm_words = _norm_words_for_spans(words)

    out_lines = []
    pos = 0
    for idx, line in enumerate(lyric_lines):
        text = line.strip()
        if idx < len(lines):
            lt = lines[idx]
        else:
            lt = LineTimestamp(line=text, start=0.0)

        span = spans[idx] if idx < len(spans) else None
        if span is not None:
            span_words = norm_words[span[0]:span[1] + 1]
        else:
            span_words = []

        char_times = _char_times_for_line(text, lt.start, span_words,
                                          _next_start(lines, idx))
        out_lines.append({
            "start": pos,
            "end": pos + len(text) - 1,
            "chars": char_times,
        })
        pos += len(text)

    return json.dumps({"lines": out_lines})


def _next_start(lines: list[LineTimestamp], idx: int) -> Optional[float]:
    for j in range(idx + 1, len(lines)):
        if lines[j].start > 0 or True:
            return lines[j].start
    return None


def _char_times_for_line(
    text: str,
    line_start: float,
    span_words: list[WordTimestamp],
    next_start: Optional[float],
) -> list[float]:
    """One timestamp per character, interpolated across the matched words."""
    chars = list(text)
    if not chars:
        return []

    if span_words:
        # Proportional char budget per word based on its normalized length
        parts = []
        counts = [max(1, len(_normalize(w.word))) for w in span_words]
        total = sum(counts)
        body = [c for c in chars if not c.isspace()]
        # assign chars to words proportionally
        assigned = []
        start_at = 0
        for wi, cnt in enumerate(counts):
            take = round(len(body) * cnt / total)
            if wi == len(counts) - 1:
                take = len(body) - start_at
            assigned.append(body[start_at:start_at + take])
            start_at += take
        # build per-word time ranges
        times = []
        for wrepo, w in zip(assigned, span_words):
            n = max(1, len(wrepo))
            for k in range(len(wrepo)):
                t = w.start + (w.end - w.start) * (k / n)
                times.append(round(t, 3))
        # interleave back over original chars (spaces get previous time)
        out = []
        ti = 0
        for c in chars:
            if c.isspace():
                out.append(out[-1] if out else round(line_start, 3))
            else:
                out.append(times[ti] if ti < len(times) else round(times[-1], 3))
                ti += 1
        return out

    # Fallback: even spread over [line_start, next line start or +2s]
    end = next_start if next_start is not None and next_start > line_start else line_start + 2.0
    n = len(chars)
    return [round(line_start + (end - line_start) * (i / n), 3) for i in range(n)]


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
    temperature: float = 0.0,
    beam_size: int = 5,
    best_of: int = 5,
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
        if language is None:
            script_lang = detect_language_from_text(lyrics_text)
            if script_lang:
                language = script_lang
                result.detected_language = language
                print(f"Detected language from lyrics script: {language}", flush=True)
                if progress_callback:
                    progress_callback("detecting_language", 100, f"Detected from text: {language}")
            else:
                if progress_callback:
                    progress_callback("detecting_language", 0, "Detecting language (tiny model)...")
                try:
                    language, prob = detect_language_tiny(wav_path)
                    print(f"Detected language: {language} ({prob:.0%})", flush=True)
                    if progress_callback:
                        progress_callback("detecting_language", 100, f"Detected: {language} ({prob:.0%})")
                except Exception:
                    language = None  # fall back to whisper's own detection
                else:
                    result.detected_language = language

        words = transcribe_with_whisper(
            wav_path, model_size, language, progress_callback=progress_callback,
            temperature=temperature, beam_size=beam_size, best_of=best_of,
        )

        if not words:
            result.warnings.append("Whisper returned no word timestamps")
            return result

        # Match lyrics to words
        if progress_callback:
            progress_callback("matching", 0, "Matching lyrics...")
        line_timestamps, warnings, spans = match_lyrics_to_words(
            lyrics_lines, words, return_spans=True)
        result.warnings.extend(warnings)
        result.lines = line_timestamps
        result.spans = spans
        # Keep raw transcription words with the same offset applied as the LRC
        result.words = [
            WordTimestamp(
                word=w.word,
                start=max(0.0, w.start + offset),
                end=max(0.0, w.end + offset),
            )
            for w in words
        ]
        result.sync_text = sync_json(line_timestamps, lyrics_lines, spans, result.words)

        # Format as LRC
        result.lrc_text = format_lrc(line_timestamps, offset=offset)

        if progress_callback:
            progress_callback("done", 100, "Done!")

    finally:
        # Clean up temp WAV
        if os.path.exists(wav_path):
            os.remove(wav_path)

    return result
