"""Fetch synced lyrics from the Paxsenix Lyrically API (Apple Music TTML).

Only the ``/apple-music/lyrics`` endpoint is currently unrestricted; every
other provider and all ``/search`` endpoints return 403. Apple TTML comes
in two flavours:

- ``itunes:timing="Line"`` -- one ``<p begin end>`` per lyric line.
  Produces LRC only.
- ``itunes:timing="Word"`` -- lines additionally carry ``<span begin end>``
  word timings. Produces LRC plus per-character sync JSON in the same shape
  as the aligner's ``output_sync.json``.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from logger import log

BASE_URL = "https://lyrics.paxsenix.org"
USER_AGENT = "lrc-sync/1.0"

_TTML_NS = "http://www.w3.org/ns/ttml"
_ITUNES_NS = "http://music.apple.com/lyric-ttml-internal"


def extract_apple_id(raw: str) -> str:
    """Return the numeric Apple Music track ID from a raw ID or share URL."""
    text = (raw or "").strip()
    if text.isdigit():
        return text
    match = re.search(r"/(\d+)(?:[/?#]|$)", text)
    if match:
        return match.group(1)
    raise ValueError("Expected an Apple Music track ID or share URL")


def extract_ttml_from_envelope(obj: dict) -> str:
    """Pull the raw TTML document out of an API response envelope."""
    if isinstance(obj, dict) and obj.get("type") == "TTML" and obj.get("content"):
        return obj["content"]
    message = ""
    if isinstance(obj, dict):
        message = str(obj.get("message") or obj.get("detail") or "")
    raise RuntimeError(f"Paxsenix lyrics unavailable: {message or 'unknown error'}")


def _parse_time(value, default: float = 0.0) -> float:
    """Parse a TTML time: seconds ("31.146") or clock ("1:00.862")."""
    if value is None:
        return default
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    parts = text.split(":")
    try:
        total = float(parts[-1])
        multiplier = 60.0
        for part in reversed(parts[:-1]):
            total += float(part) * multiplier
            multiplier *= 60.0
        return total
    except ValueError:
        return default


def _float(value, default: float = 0.0) -> float:
    return _parse_time(value, default)


def _is_cjk_char(ch: str) -> bool:
    """Mirror of aligner._contains_cjk, for a single character."""
    o = ord(ch)
    return (
        0x3040 <= o <= 0x30FF  # hiragana + katakana
        or 0x31F0 <= o <= 0x31FF  # katakana phonetic extensions
        or 0x3400 <= o <= 0x4DBF  # CJK extension A
        or 0x4E00 <= o <= 0x9FFF  # CJK unified ideographs
        or 0xAC00 <= o <= 0xD7AF  # hangul syllables
    )


_NO_SPACE_AFTER = set("\"'“‘([{")
_NO_SPACE_BEFORE = set(".,!?:;%)]}'\"’”、。〈〉「」『』")


def _needs_space(prev: str, nxt: str) -> bool:
    return (
        bool(prev)
        and not prev.isspace()
        and not nxt.isspace()
        and not _is_cjk_char(prev)
        and not _is_cjk_char(nxt)
        and prev not in _NO_SPACE_AFTER
        and nxt not in _NO_SPACE_BEFORE
    )


def _join_spans(texts: list[str]) -> str:
    """Join word-span texts, restoring spaces Apple TTML spans omit.

    Spans usually carry their own whitespace ("Hello "), but many tracks
    emit bare words ("Mirror" "on"). Insert a space at a bare boundary
    unless it touches whitespace already, CJK (which takes no spaces),
    or punctuation that binds tight ("I'm", "yeah,").
    """
    parts: list[str] = []
    for text in texts:
        if parts and text and _needs_space(parts[-1][-1:], text[:1]):
            parts.append(" ")
        parts.append(text)
    return "".join(parts)


def parse_ttml(xml_text: str) -> dict:
    """Parse TTML into ``{"timing": "line"|"word", "lines": [...]}``.

    Each line is ``{"start", "end", "text", "words"}`` where ``words`` is
    ``None`` for line-timed tracks or a list of
    ``{"start", "end", "text"}`` for word-timed ones.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"Invalid TTML: {e}")
    if not root.tag.endswith("tt"):
        raise ValueError("Invalid TTML: root element is not <tt>")

    timing = root.get(f"{{{_ITUNES_NS}}}timing", "Line").lower()
    word_timed = timing == "word"

    lines = []
    for p in root.findall(f".//{{{_TTML_NS}}}p"):
        start = _float(p.get("begin"))
        end = _float(p.get("end"))
        words = None
        if word_timed:
            words = []
            for span in p.findall(f"{{{_TTML_NS}}}span"):
                words.append({
                    "start": _float(span.get("begin"), start),
                    "end": _float(span.get("end"), start),
                    "text": span.text or "",
                })
            text = _join_spans([w["text"] for w in words])
        else:
            text = "".join(p.itertext()).strip()
        if text:
            lines.append({"start": start, "end": end, "text": text, "words": words})

    return {"timing": "word" if word_timed else "line", "lines": lines}


def to_lrc(parsed: dict) -> str:
    """Render parsed lines as LRC text."""
    out = []
    for line in parsed["lines"]:
        cs = int(round(max(0.0, line["start"]) * 100))
        m, rem = divmod(cs, 6000)
        s = rem / 100.0
        out.append(f"[{m:02d}:{s:05.2f}]{line['text']}")
    return "\n".join(out)


def to_sync_json(parsed: dict, noise: float = 0.02, seed=None) -> str:
    """Render word-timed lines as output_sync.json-compatible JSON.

    ``{"lines": [{"start", "end", "chars"}]}`` with one start time per
    character, matching the aligner's per-character sync shape. Word
    durations are split proportionally across their non-space characters;
    separator spaces restored between spans are interpolated between the
    neighbouring word boundaries. A small uniform jitter (default ±0.02s)
    is added per character and clamped back to monotonic non-decreasing;
    pass ``noise=0.0`` for exact timings (and ``seed=`` for reproducible
    jitter in tests).
    """
    import itertools
    import random

    if parsed["timing"] != "word":
        raise ValueError("Character sync requires a word-timed track")

    rng = random.Random(seed)
    out_lines = []
    pos = 0
    for line in parsed["lines"]:
        text = line["text"]
        words = line["words"] or []
        chars: list[float] = []
        for i, word in enumerate(words):
            body = [c for c in word["text"] if not c.isspace()]
            n = max(1, len(body))
            times = [
                word["start"] + (word["end"] - word["start"]) * (k / n)
                for k in range(len(body))
            ]
            ti = 0
            for c in word["text"]:
                if c.isspace():
                    chars.append(chars[-1] if chars else line["start"])
                else:
                    chars.append(times[ti])
                    ti += 1
            # Restored separator spaces carry no timing of their own:
            # interpolate across the gap between the word boundaries.
            if i < len(words) - 1:
                nxt = words[i + 1]
                midpoint = (word["end"] + nxt["start"]) / 2.0
                while len(chars) < len(text) and text[len(chars)].isspace():
                    chars.append(midpoint)
        if noise > 0:
            chars = [c + rng.uniform(-noise, noise) for c in chars]
        monotonic = list(itertools.accumulate(chars, max))
        out_lines.append({
            "start": pos,
            "end": pos + len(text) - 1,
            "chars": [round(c, 3) for c in monotonic],
        })
        pos += len(text)

    return json.dumps({"lines": out_lines})


def fetch_ttml(track_id: str, timeout: int = 30) -> str:
    """Fetch the raw TTML document for an Apple Music track ID."""
    query = urllib.parse.urlencode({"id": track_id, "ttml": "true"})
    req = urllib.request.Request(
        f"{BASE_URL}/apple-music/lyrics?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    import time

    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                envelope = json.loads(resp.read().decode("utf-8"))
            if attempt > 1:
                log("INFO", f"Paxsenix retry succeeded on attempt {attempt}/5")
            break
        except urllib.error.HTTPError as e:
            try:
                envelope = json.loads(e.read().decode("utf-8"))
            except Exception:
                envelope = {}
            detail = ""
            if isinstance(envelope, dict):
                detail = str(envelope.get("message") or envelope.get("detail") or "")
            if e.code == 503:
                if attempt < 5:
                    log("WARN", f"Paxsenix busy, retry {attempt}/5...")
                    time.sleep(1.0 * (2 ** (attempt - 1)))
                    continue
                raise RuntimeError("Paxsenix lyrics service is busy; retry later")
            if e.code == 404:
                raise RuntimeError("No lyrics found for this track")
            raise RuntimeError(f"Paxsenix request failed: HTTP {e.code} {detail}".strip())
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Paxsenix request failed: {e}")
    return extract_ttml_from_envelope(envelope)
