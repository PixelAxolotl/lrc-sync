"""
Core alignment pipeline: audio + lyrics → synced LRC file.
"""

import os
import re
import subprocess
import sys
import tempfile
from collections import Counter

# Prefer the HF mirror so downloads work where huggingface.co is flaky
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class WordTimestamp:
    """A single word with its start and end time."""
    word: str
    start: float
    end: float
    confidence: Optional[float] = None


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
    from ffmpeg_setup import find_ffmpeg
    return find_ffmpeg()


def convert_to_wav(audio_path: str, output_path: Optional[str] = None) -> str:
    """Convert any audio format to 16kHz mono WAV using ffmpeg."""
    if output_path is None:
        output_path = tempfile.mktemp(suffix=".wav")

    from ffmpeg_setup import ensure_ffmpeg
    try:
        ffmpeg = ensure_ffmpeg()
    except RuntimeError as e:
        raise RuntimeError(str(e))

    cmd = [
        ffmpeg, "-y", "-i", audio_path,
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")
    return output_path


_LOCAL_MODELS_DIR = Path(__file__).parent / "whisper_models"

# English-only Whisper variants. Faster to load and slightly more accurate
# on English, but they cannot transcribe other languages — Whisper will
# output garbage/empty timestamps for e.g. Japanese. Callers should warn.
EN_ONLY_MODELS = frozenset({"tiny.en", "base.en", "small.en", "medium.en"})


def is_english_only_model(model_size: str) -> bool:
    """True if the model is an English-only (.en) Whisper variant."""
    return model_size in EN_ONLY_MODELS

_tiny_model = None



def _model_source(model_size: str) -> str:
    """Prefer a local model folder, but only when it actually holds weights.

    A folder that exists without ``model.bin`` is a partial/interrupted
    download; returning it would shadow the real download and fail to load.
    In that case fall back to the model id so faster-whisper fetches it.
    """
    local = _LOCAL_MODELS_DIR / model_size
    if (local / "model.bin").exists():
        return str(local)
    return model_size


def _expected_cache_dir(model_size: str) -> Optional[str]:
    """Return the Hugging Face cache dir name for a model id, or None.

    e.g. ``large-v3`` -> ``models--Systran--faster-whisper-large-v3``.
    """
    try:
        from faster_whisper.utils import _MODELS
    except Exception:
        return None
    repo = _MODELS.get(model_size)
    if not repo:
        return None
    return "models--" + repo.replace("/", "--")

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


_MODEL_CACHE: dict = {}  # model name -> WhisperModel (reloading costs seconds/GB)


def _load_whisper_model(name: str, progress_callback=None):
    """Load a faster-whisper model; fall back to ModelScope if HF fails.

    Results are memoized per process: loading re-reads the full weight set
    from disk, which dominates runtime when sweeping several configurations
    over the same track.
    """
    cached = _MODEL_CACHE.get(name)
    if cached is not None:
        print(f"Reusing loaded faster-whisper model '{name}'.", flush=True)
        return cached

    from faster_whisper import WhisperModel
    common = dict(device="cpu", compute_type="int8",
                  download_root=str(_LOCAL_MODELS_DIR))
    print(f"Loading faster-whisper model '{name}' (CPU/int8)...", flush=True)
    local = _LOCAL_MODELS_DIR / name
    download_needed = not Path(_model_source(name)).exists() and not _already_downloaded(name)
    if download_needed:
        _maybe_prompt_for_hf_token(name)
        if progress_callback:
            progress_callback("downloading", 0, f"Downloading '{name}' from Hugging Face...")
    if download_needed:
        print(f"Model '{name}' not found locally — downloading from Hugging Face...", flush=True)
    import threading, time
    stop = threading.Event()
    prev_mb = -1.0

    def _report_size():
        nonlocal prev_mb
        while not stop.wait(2.0):
            try:
                mb = sum(f.stat().st_size for f in _LOCAL_MODELS_DIR.rglob("*") if f.is_file()) / 1e6
                if mb > prev_mb + 0.5:  # only print when it actually grows
                    delta = mb if prev_mb < 0 else mb - prev_mb
                    print(f"  downloaded {delta:.1f} MB (total in whisper_models: {mb:.1f} MB)...", flush=True)
                    if progress_callback:
                        progress_callback("downloading", 0, f"Downloading '{name}'… {mb:.0f} MB received")
                    prev_mb = mb
            except Exception:
                pass

    if download_needed:
        t = threading.Thread(target=_report_size, daemon=True)
        t.start()

    try:
        model = WhisperModel(_model_source(name), **common)
        print(f"Model '{name}' ready.", flush=True)
        _MODEL_CACHE[name] = model
        return model
    except Exception as e:
        print(f"HF download/load failed for '{name}' ({e}).", flush=True)
    finally:
        stop.set()
    raise RuntimeError(
        f"Could not obtain faster-whisper model '{name}' from HF (mirror). "
        "Pre-download it into whisper_models/.")


def _already_downloaded(name: str) -> bool:
    try:
        if not _LOCAL_MODELS_DIR.exists():
            _LOCAL_MODELS_DIR.mkdir(parents=True, exist_ok=True)
            return False
        # A bare local folder counts only when it actually holds weights.
        local = _LOCAL_MODELS_DIR / name
        if (local / "model.bin").exists():
            return True
        # Hugging Face cache dir for this exact model (substring matching would
        # let e.g. the large-v3-turbo cache satisfy a request for large-v3).
        expected = _expected_cache_dir(name)
        if expected and (_LOCAL_MODELS_DIR / expected).exists():
            return True
    except Exception:
        return False
    return False


TOKEN_PROVIDER = None  # optional callable(model_name) -> token or ""


def _maybe_prompt_for_hf_token(name: str):
    """Ask for an HF token when a model still needs downloading (CLI only)."""
    if _already_downloaded(name):
        return
    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN"):
        return
    print(
        f"Model '{name}' is not downloaded yet. Hugging Face may require an access token.\n"
        "Paste an HF token to use, or press Enter / 'n' to continue without one.",
        flush=True,
    )
    try:
        import sys
        if TOKEN_PROVIDER is not None:
            token = TOKEN_PROVIDER(name).strip()
            if token and token.lower() not in ("n", "no", "skip"):
                os.environ["HF_TOKEN"] = token
                print("HF_TOKEN set from web UI.", flush=True)
            else:
                print("User chose to continue without a token.", flush=True)
            return
        if not sys.stdin.isatty():
            print("No interactive terminal detected; proceeding without a token.", flush=True)
            return
        token = input("HF token (or Enter / n to skip): ").strip()
    except (EOFError, OSError):
        return
    if token and token.lower() not in ("n", "no", "skip"):
        os.environ["HF_TOKEN"] = token
        print("HF_TOKEN set for this session.", flush=True)
    else:
        print("Continuing without a token.", flush=True)


def detect_language_tiny(wav_path: str) -> tuple[str, float]:
    """Detect audio language with a tiny CPU model (fast), for auto mode."""
    global _tiny_model
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    if _tiny_model is None:
        _tiny_model = _load_whisper_model("tiny")
    audio = decode_audio(wav_path, sampling_rate=16000)
    language, probability, _ = _tiny_model.detect_language(audio)
    return language, probability


def _extract_vocals(wav_path: str, cache_path: Optional[str] = None) -> str:
    """Separate vocals from the mix with Demucs; returns path to vocals WAV.

    When cache_path is given and exists, reuse it. Otherwise run demucs and
    copy the vocals stem to cache_path for reuse on subsequent runs.
    """
    if cache_path and Path(cache_path).exists():
        return cache_path
    try:
        import demucs  # type: ignore  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "Vocal separation requires demucs (pip install demucs). "
            "Install it or disable separate_vocals."
        )
    out_dir = tempfile.mkdtemp(prefix="lrc_vocals_")
    import subprocess as _sp
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "--two-stems", "vocals",
        "-o", out_dir, wav_path,
    ]
    proc = _sp.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"demucs failed: {proc.stderr[-500:]}")
    matches = list(Path(out_dir).rglob("vocals.wav"))
    if not matches:
        raise RuntimeError("demucs produced no vocals.wav output")
    if cache_path:
        import shutil
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(matches[0], cache_path)
        return cache_path
    return str(matches[0])


def _build_initial_prompt(lyrics_text: str, max_chars: int = 200) -> Optional[str]:
    """Lyrics as a Whisper decoder prompt: biases toward the song's vocabulary."""
    text = " ".join(l.strip() for l in lyrics_text.splitlines() if l.strip())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:max_chars]


def _is_looped_segment(text_words: list[str]) -> bool:
    """Detect within-segment repetition loops (e.g. 歌詞・歌詞・歌詞…).

    Legit choruses repeat short phrases, so only flag segments with at
    least 6 words where uniqueness collapses or one token dominates.
    """
    toks = [_normalize(w) for w in text_words]
    toks = [t for t in toks if t]
    if len(toks) < 6:
        return False
    if len(set(toks)) / len(toks) < 0.3:
        return True
    top = Counter(toks).most_common(1)[0][1]
    return top / len(toks) >= 0.6


def transcribe_with_whisper(
    wav_path: str,
    model_size: str = "small",
    language: Optional[str] = None,
    progress_callback=None,
    temperature: float = 0.0,
    beam_size: int = 8,
    best_of: int = 5,
    initial_prompt: Optional[str] = None,
    fallback_temperatures: tuple = (0.2, 0.4),
    drop_looped: bool = True,
) -> tuple:
    """Run faster-whisper with word-level timestamps.

    Returns (words, skipped_looped_segments).

    drop_looped: discard segments that look like repetition hallucinations.
        Off by default being risky: fast rap sections and legitimate repeated
        choruses can trip the detector, and a discarded segment removes the
        words for every lyric line it covered, which no amount of matching can
        recover. Set False to keep everything.
    """
    from faster_whisper import WhisperModel

    if progress_callback:
        progress_callback("loading_model", 0, "Loading Whisper model (downloads on first run)...")

    model = _load_whisper_model(model_size, progress_callback=progress_callback)

    if progress_callback:
        progress_callback("transcribing", 0, "Transcribing...")

    # Temperature fallback: when the first temperature decodes a segment
    # with a high compression ratio (repetition loop), low logprob, or high
    # no-speech probability, faster-whisper retries it at the next
    # temperature instead of keeping the hallucination. A single float
    # disables this, so always pass a tuple starting at the requested temp.
    if isinstance(temperature, (list, tuple)):
        temperature_param = tuple(temperature)
    elif fallback_temperatures:
        temperature_param = (temperature,) + tuple(fallback_temperatures)
    else:
        temperature_param = temperature

    segments, info = model.transcribe(
        wav_path,
        word_timestamps=True,
        language=language,
        temperature=temperature_param,
        beam_size=beam_size,
        best_of=best_of,
        initial_prompt=initial_prompt,
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        # NOTE: vad_filter must stay OFF for sung music. Silero VAD
        # classifies sung vocals over instruments as non-speech and
        # discards ~90% of the song (verified: 14 words with VAD vs
        # 236 words without, on the same track).
        vad_filter=False,
        # NOTE: condition_on_previous_text MUST stay OFF for sung music.
        # With it on, Whisper feeds its own output back as context; a single
        # hallucination (e.g. a "作詞・作曲・歌詞" credits block) then loops for
        # the entire track. Verified on Hanataba (milet): medium + beam5
        # produced 1359 words that were 0% unique and contained none of the
        # real lyrics, versus 247 words with the real lyrics once disabled.
        condition_on_previous_text=False,
    )

    words: list[WordTimestamp] = []
    skipped_looped = 0
    total_duration = info.duration if hasattr(info, 'duration') else 0

    for segment in segments:
        seg_words = [w.word.strip() for w in (segment.words or [])]
        if drop_looped and seg_words and _is_looped_segment(seg_words):
            skipped_looped += 1
            continue
        if segment.words:
            for w in segment.words:
                words.append(WordTimestamp(
                    word=w.word.strip(),
                    start=w.start,
                    end=w.end,
                    confidence=getattr(w, "probability", None),
                ))
        if progress_callback and total_duration > 0:
            pct = min(100, int((segment.end / total_duration) * 100))
            progress_callback("transcribing", pct, f"Transcribing... {pct}%")

    if progress_callback:
        progress_callback("transcribing", 100, "Transcription complete")

    return words, skipped_looped


def _normalize(text: str) -> str:
    """Normalize text for fuzzy matching: NFKC-fold, lowercase, strip punctuation.

    NFKC matters for CJK: lyric sources (LRCLIB, uta-net, ...) are full of
    full-width kana, full-width latin and ideographic spaces, while Whisper
    transcribes the half-width forms. Without folding, visually identical
    characters never compare equal and similarity is depressed across the board.
    """
    import unicodedata
    folded = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"[^\w\s]", "", folded.lower()).strip()


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
    accept_threshold: float = 0.2,
    similarity_mode: str = "bigram",
    conf_floor: float = 0.15,
    est_cjk_divisor: int = 2,
    window_pad: int = 8,
    lookahead_mult: int = 3,
    lookahead_extra: int = 10,
    backtrack: int = 5,
    advance_on_fail: bool = False,
    interpolate_fallback: bool = True,
    fallback_gap: float = 1.0,
    anchor_shift: float = 0.0,
    min_anchor_ratio: float = 0.5,
):
    """
    Fuzzy-match lyric lines against Whisper word timestamps.
    Returns line-level timestamps and any warnings. With return_spans=True,
    also returns a per-line span (start_idx, end_idx) into `words` or None.

    Defaults are the tuned values (validated at 82.7% of lines within 1s on a
    19-track Japanese corpus scored against LRCLIB); pass similarity_mode="sets"
    plus interpolate_fallback=False to restore the previous behaviour.

    similarity_mode
        "sets"  legacy bag-of-characters / bag-of-words overlap. Order
                insensitive, so common kana (と/い/て/は) make short lines
                match almost any window.
        "bigram" (default) character-bigram F1. Still segmentation-agnostic
                (works however Whisper chunked the words) but order sensitive
                and far more discriminative on CJK.
        "both"  max of the two.
    advance_on_fail
        Move the search cursor forward when a line fails to match. Without it
        a single failure leaves the cursor stale, so the search window no
        longer reaches the real words and every later line fails too - the
        failure cascades to the end of the track.
    interpolate_fallback
        Place unmatched lines by linear interpolation between their nearest
        matched neighbours instead of "previous line + 1s". The legacy step
        makes consecutive misses ramp 1s apart, which is arbitrary; monotonic
        song order is a far better prior.
    """
    warnings: list[str] = []
    result: list[LineTimestamp] = []
    spans: list = []

    # Normalize whisper words; drop near-zero confidence words entirely
    norm_words = [(w, _normalize(w.word)) for w in words]
    norm_words = [
        (w, nw) for w, nw in norm_words
        if nw and (w.confidence is None or w.confidence >= conf_floor)
    ]

    word_idx = 0
    total_words = len(norm_words)

    # (text, start, span) per kept lyric line; None marks an unmatched line.
    picks: list = []
    kept: list[str] = []

    for line in lyrics:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        norm_line = _normalize(line_stripped)
        if not norm_line:
            # A line that normalizes to nothing - a bare "♪", or pure
            # punctuation - still needs an entry in the output, otherwise the
            # result has fewer lines than the input and every later line is
            # shifted relative to its source. Give it an interpolated
            # timestamp like any other unmatched line.
            kept.append(line_stripped)
            picks.append(None)
            continue
        kept.append(line_stripped)

        best_start = None
        best_score = 0.0
        best_end_idx = word_idx
        best_i = None

        # Estimate how many whisper words a line spans.
        # CJK text has no spaces, so estimate from character count instead.
        if _contains_cjk(norm_line):
            est_words = max(2, len(norm_line.replace(" ", "")) // est_cjk_divisor)
        else:
            est_words = len(norm_line.split())

        # Search through remaining words
        search_start = max(0, word_idx - backtrack)  # allow some backtracking
        search_end = min(total_words, word_idx + est_words * lookahead_mult + lookahead_extra)

        for i in range(search_start, search_end):
            candidate_words = []
            for j in range(i, min(i + est_words + window_pad, total_words)):
                candidate_words.append(norm_words[j][1])
                candidate_text = " ".join(candidate_words)
                score = _similarity(norm_line, candidate_text, mode=similarity_mode)
                if score > best_score:
                    best_score = score
                    best_start = norm_words[i][0].start
                    best_end_idx = j
                    best_i = i

        matched = False
        if best_start is not None and best_score > accept_threshold:
            # Enforce monotonic timestamps: never go back in time.
            # A match earlier than the previous accepted line is spurious
            # (e.g. a repeated chorus fragment) - fall back instead.
            prev_start = next(
                (p["start"] for p in reversed(picks) if p is not None), None)
            if prev_start is None or best_start >= prev_start:
                matched = True
                # anchor_shift nudges the line start later. Whisper's first
                # word in a span tends to begin slightly before the sung
                # syllable, so a small positive shift can tighten alignment.
                best_start = max(prev_start if prev_start is not None else 0.0,
                                 best_start + anchor_shift)

        if matched:
            picks.append({
                "start": best_start,
                "span": (best_i, best_end_idx) if best_i is not None else None,
            })
            word_idx = best_end_idx + 1
        else:
            picks.append(None)
            if advance_on_fail:
                # Keep the cursor moving so later lines can still reach their
                # own words instead of all cascading into the fallback.
                if best_i is not None:
                    word_idx = max(word_idx, best_i + 1)
                else:
                    word_idx = min(total_words, word_idx + est_words)

    if interpolate_fallback:
        _interpolate_gaps(picks, kept, fallback_gap)

    # Materialise, enforcing monotonicity even after interpolation.
    prev_start = None
    for text, pick in zip(kept, picks):
        if pick is None:
            warnings.append(f"Could not match line: '{text}'")
            start = (prev_start + fallback_gap) if prev_start is not None else 0.0
            span = None
        else:
            start = pick["start"]
            span = pick["span"]
            if prev_start is not None and start < prev_start:
                start = prev_start
        result.append(LineTimestamp(line=text, start=max(0.0, start)))
        spans.append(span)
        prev_start = result[-1].start

    fallback_count = sum(1 for s in spans if s is None)
    if result and fallback_count / len(result) > 0.25:
        warnings.append(
            f"Over 25% of lyric lines did not match the transcription "
            f"(fallback +1s timestamps used). Check the language/model settings."
        )
    if return_spans:
        return result, warnings, spans
    return result, warnings


def _interpolate_gaps(picks: list, kept: list[str], fallback_gap: float,
                      min_anchor_ratio: float = 0.5) -> None:
    """Fill unmatched lines by linear interpolation between matched neighbours."""
    n = len(picks)
    matched_idx = [i for i, p in enumerate(picks) if p is not None]
    if not matched_idx:
        return
    # Typical line spacing, used when a run touches the start/end of the song.
    gaps = [
        picks[b]["start"] - picks[a]["start"]
        for a, b in zip(matched_idx, matched_idx[1:])
        if b - a > 0 and picks[b]["start"] > picks[a]["start"]
    ]
    typical = sorted(gaps)[len(gaps) // 2] if gaps else fallback_gap

    for i in range(n):
        if picks[i] is not None:
            continue
        prev_i = next((j for j in range(i - 1, -1, -1) if picks[j] is not None), None)
        next_i = next((j for j in range(i + 1, n) if picks[j] is not None), None)
        if prev_i is None and next_i is None:
            continue
        if prev_i is None:
            t = picks[next_i]["start"] - typical * (next_i - i)
        elif next_i is None:
            t = picks[prev_i]["start"] + typical * (i - prev_i)
        else:
            span_lines = next_i - prev_i
            span_time = picks[next_i]["start"] - picks[prev_i]["start"]
            # If the two anchors are closer together than the typical spacing
            # for that many lines, at least one anchor is wrong (typically a
            # mis-matched line, or a run of lines the transcript never
            # covered). Interpolating across it would compress the whole run
            # into a couple of seconds, so extrapolate from `prev_i` using
            # typical spacing instead.
            if span_time < typical * span_lines * min_anchor_ratio:
                t = picks[prev_i]["start"] + typical * (i - prev_i)
            else:
                t = picks[prev_i]["start"] + span_time * (i - prev_i) / span_lines
        picks[i] = {"start": max(0.0, t), "span": None}


def _char_ngrams(text: str, n: int = 2) -> set:
    """Character n-grams with spaces removed (CJK has no word delimiters)."""
    s = text.replace(" ", "")
    if not s:
        return set()
    if len(s) < n:
        return {s}
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _bigram_f1(a: str, b: str) -> float:
    """Order-sensitive character-bigram F1 score in [0, 1].

    Segmentation-agnostic (a line split into different words by Whisper still
    yields the same bigrams) yet still requires the characters to appear in the
    right order, unlike the legacy set-overlap score.
    """
    ga, gb = _char_ngrams(a), _char_ngrams(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    if not inter:
        return 0.0
    precision = inter / len(gb)
    recall = inter / len(ga)
    return 2.0 * precision * recall / (precision + recall)


def _similarity(a: str, b: str, mode: str = "sets") -> float:
    """Overlap similarity, falling back to character-level for CJK text.

    mode="sets"   legacy behaviour (bag of chars / bag of words)
    mode="bigram" character-bigram F1
    mode="both"   best of the two
    """
    if mode == "bigram":
        return _bigram_f1(a, b)

    if _contains_cjk(a) or _contains_cjk(b):
        a_chars = set(a.replace(" ", ""))
        b_chars = set(b.replace(" ", ""))
        if not a_chars or not b_chars:
            legacy = 0.0
        else:
            overlap = a_chars & b_chars
            legacy = len(overlap) / max(len(a_chars), len(b_chars))
    else:
        a_words = set(a.split())
        b_words = set(b.split())
        if not a_words or not b_words:
            legacy = 0.0
        else:
            overlap = a_words & b_words
            legacy = len(overlap) / max(len(a_words), len(b_words))

    if mode == "both":
        return max(legacy, _bigram_f1(a, b))
    return legacy


def words_to_json(words: list[WordTimestamp], offset: float = 0.0) -> str:
    """Serialize word timestamps as JSON: {"words": [{word, start, end}]}."""
    import json

    return json.dumps({"words": [
        {
            "word": w.word,
            "start": round(max(0.0, w.start + offset), 3),
            "end": round(max(0.0, w.end + offset), 3),
            **({"confidence": round(w.confidence, 3)} if w.confidence is not None else {}),
        }
        for w in words
    ]})


def _norm_words_for_spans(words: list[WordTimestamp]) -> list[WordTimestamp]:
    return [
        w for w in words
        if _normalize(w.word) and (w.confidence is None or w.confidence >= 0.15)
    ]


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
    merge_consecutive: bool = False,
) -> str:
    """Format line-level timestamps as LRC text.

    Merging is OFF by default: consecutive lines that share a timestamp
    (e.g. rapid-fire opening lines all stamped 00:00) are emitted on their
    own lines. Duplicate timestamps are valid LRC and most players simply
    advance to the later line. Pass merge_consecutive=True for the old
    "A / B" collapsing behavior.
    """
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
    model_size: str = "medium",
    language: Optional[str] = None,
    offset: float = 0.0,
    progress_callback=None,
    temperature: float = 0.0,
    beam_size: int = 5,
    best_of: int = 5,
    separate_vocals: bool = False,
    initial_prompt: Optional[str] = None,
    fallback_temperatures: tuple = (0.2, 0.4),
    drop_looped: bool = True,
    similarity_mode: str = "bigram",
    accept_threshold: float = 0.2,
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
        separate_vocals: Strip instrumentals with Demucs before transcribing

    Returns:
        AlignmentResult with lines, LRC text, and warnings
    """
    result = AlignmentResult()

    # Parse lyrics
    lyrics_lines = [l for l in lyrics_text.split("\n") if l.strip()]
    if not lyrics_lines:
        result.warnings.append("No lyrics provided")
        return result

    # Disclaimer for English-only models: they only work on English audio.
    if is_english_only_model(model_size) and (language is None or language != "en"):
        # language=None means auto-detect, which an .en model can't do
        # reliably either — flag it unless the user explicitly forced en.
        if language is None:
            result.warnings.append(
                f"Model '{model_size}' is English-only: non-English lyrics/audio "
                f"will transcribe poorly. Use a multilingual model (tiny/base/small/"
                f"medium/large-v3) for other languages."
            )
        else:
            result.warnings.append(
                f"Model '{model_size}' is English-only but language='{language}' "
                f"was requested: transcription will be poor. Use a multilingual "
                f"model instead."
            )

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

        if separate_vocals:
            try:
                if progress_callback:
                    progress_callback("separating_vocals", 0, "Separating vocals (demucs)...")
                # Cache vocals next to the source audio so reruns are instant
                voc_cache = Path(audio_path).parent / (Path(audio_path).stem + "_vocals.wav")
                vocals_path = _extract_vocals(wav_path, cache_path=str(voc_cache))
                if progress_callback:
                    progress_callback("separating_vocals", 100, "Vocals separated")
            except Exception as e:
                result.warnings.append(f"Vocal separation failed, using full mix: {e}")
                vocals_path = wav_path
        else:
            vocals_path = wav_path

        words, skipped_looped = transcribe_with_whisper(
            vocals_path, model_size, language, progress_callback=progress_callback,
            temperature=temperature, beam_size=beam_size, best_of=best_of,
            initial_prompt=initial_prompt,
            fallback_temperatures=fallback_temperatures,
            drop_looped=drop_looped,
        )
        if skipped_looped:
            result.warnings.append(
                f"Skipped {skipped_looped} looped transcription segment(s) "
                f"(repetition hallucination). Timestamps may be sparse there."
            )

        if not words:
            result.warnings.append("Whisper returned no word timestamps")
            return result

        # Match lyrics to words
        if progress_callback:
            progress_callback("matching", 0, "Matching lyrics...")
        line_timestamps, warnings, spans = match_lyrics_to_words(
            lyrics_lines, words, return_spans=True,
            similarity_mode=similarity_mode,
            accept_threshold=accept_threshold)
        result.warnings.extend(warnings)
        result.lines = line_timestamps
        result.spans = spans
        # Keep raw transcription words with the same offset applied as the LRC.
        # Preserve `confidence`: sync_json() filters words by it against the
        # SAME list match_lyrics_to_words indexed, so dropping it here would
        # silently shift every span index.
        result.words = [
            WordTimestamp(
                word=w.word,
                start=max(0.0, w.start + offset),
                end=max(0.0, w.end + offset),
                confidence=w.confidence,
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
