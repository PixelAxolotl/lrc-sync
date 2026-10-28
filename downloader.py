"""
YouTube audio downloader using yt-dlp.
"""

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).parent
DEFAULT_TEMP_DIR = PROJECT_DIR / "temp"
AUDIO_CACHE_DIR = PROJECT_DIR / "cache_audio"

# Control characters become a space, not nothing: deleting them would weld
# adjacent words together ("Song\nName" -> "SongName").
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")

# Characters Windows forbids in filenames. They become a space rather than
# nothing: deleting outright welds the surrounding words together, turning
# "Aimer Ref:rain" into "Aimer Refrain" — a different word.
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')

# Bracketed noise YouTube uploaders staple onto titles. Matched only inside
# brackets so `Song (feat. X)` keeps its parenthetical.
_NOISE_BRACKET_RE = re.compile(
    r"[\(\[\{【（]\s*([^()\[\]{}【】（）]*?)\s*[\)\]\}】）]"
)

# A bracketed group is noise only when everything in it is noise. `feat.` is
# not, so `(feat. milet)` survives while `(Lyrics)` does not.
_NOISE_WORDS = (
    "official", "mv", "m/v", "music video", "lyric video", "lyrics", "lyric",
    "video", "audio", "hd", "hq", "4k", "remaster", "remastered", "visualizer",
    "full album", "color coded", "ver.",
    # Japanese uploaders use the same noise in kanji/kana.
    "公式", "高画質", "音源", "映像", "字幕",
)

# Separators that introduce a trailing tail, e.g. `Song - Official Music Video`.
_NOISE_TAIL_SEP_RE = re.compile(r"\s+[-–—|]\s+")
_WHITESPACE_RE = re.compile(r"\s+")
_TRAILING_SEP_RE = re.compile(r"\s+[-–—|]+$")


def _is_noise_phrase(text: str) -> bool:
    """True when every word in `text` is YouTube noise (or punctuation).

    Requires at least one noise word, so a bracket like `(2024)` is kept.
    """
    lowered = text.lower()
    if not any(word in lowered for word in _NOISE_WORDS):
        return False
    # Strip known noise phrases, then whatever is left must be empty for the
    # group to count as pure noise.
    residue = lowered
    for word in _NOISE_WORDS:
        residue = residue.replace(word, " ")
    residue = re.sub(r"[^\w\s]", " ", residue, flags=re.UNICODE)
    return not residue.strip()


def sanitize_title(title: Optional[str], max_len: int = 60) -> str:
    """Turn a video title into a short, filesystem-safe filename stem.

    Strips bracketed noise ([Official MV]), drops a trailing `- Official Music
    Video` tail, removes illegal characters, and truncates at a word boundary.
    Falls back to "audio" when nothing usable survives.
    """
    if not title:
        return "audio"

    cleaned = _NOISE_BRACKET_RE.sub(
        lambda m: "" if _is_noise_phrase(m.group(1)) else m.group(0), title
    )
    # Strip a trailing tail only when everything after the last separator is
    # itself noise (`Song - Official Music Video` -> `Song`). The segment has to
    # pass the same _is_noise_phrase test as a bracket: `Artist - Song Title
    # (Official Video)` keeps its song name, because the bracket above already
    # removed the noise and what remains is the title.
    seps = list(_NOISE_TAIL_SEP_RE.finditer(cleaned))
    if seps and _is_noise_phrase(cleaned[seps[-1].end():]):
        cleaned = cleaned[:seps[-1].start()]
    cleaned = _CONTROL_CHARS.sub(" ", cleaned)
    cleaned = _ILLEGAL_FILENAME_CHARS.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()

    # A trailing separator leaves a stub like "Song -" once the tail is gone.
    cleaned = _TRAILING_SEP_RE.sub("", cleaned).strip()
    # A title of only dots or spaces ("...") is not a usable stem.
    cleaned = cleaned.strip(" .")

    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rsplit(" ", 1)[0].strip()

    return cleaned or "audio"


@dataclass
class AudioDownload:
    """A downloaded audio file plus the title it came from."""
    path: str
    title: Optional[str] = None


def _title_meta_path(cache_path: Path) -> Path:
    """Sidecar file holding the title for a cached download."""
    return cache_path.with_suffix(cache_path.suffix + ".title.json")


def _save_cache_title(cache_path: Path, title: Optional[str]) -> None:
    """Record a download's title so cache hits can still name their output."""
    try:
        _title_meta_path(cache_path).write_text(
            json.dumps({"title": title}), encoding="utf-8")
    except OSError:
        pass


def _load_cache_title(cache_path: Path) -> Optional[str]:
    try:
        data = json.loads(_title_meta_path(cache_path).read_text(encoding="utf-8"))
        return data.get("title")
    except (OSError, ValueError):
        return None


def download_audio_with_info(
    url: str,
    output_dir: Optional[str] = None,
    progress_callback=None,
) -> AudioDownload:
    """
    Download audio from a YouTube URL as MP3, returning its path and title.

    The title is cached alongside the audio, so a repeat run still gets a real
    title even though yt-dlp is never invoked on the cache-hit path.
    """
    import hashlib

    if output_dir is None:
        output_dir = str(DEFAULT_TEMP_DIR)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Cache by URL: if we already downloaded this song, reuse the cached copy
    url_key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    cache_path = AUDIO_CACHE_DIR / f"{url_key}.mp3"
    if cache_path.exists():
        out = Path(output_dir) / f"{url_key}.mp3"
        shutil.copy2(cache_path, out)
        return AudioDownload(path=str(out), title=_load_cache_title(cache_path))

    import yt_dlp

    outtmpl = str(Path(output_dir) / "%(title)s.%(ext)s")

    def _progress_hook(d):
        if not progress_callback:
            return
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                pct = min(100, int((downloaded / total) * 100))
                progress_callback("downloading", pct, f"Downloading... {pct}%")
        elif d["status"] == "finished":
            progress_callback("downloading", 100, "Download complete, converting...")

    def _pp_hook(d):
        if not progress_callback:
            return
        if d["status"] == "started":
            progress_callback("extracting", 0, "Extracting audio...")
        elif d["status"] == "finished":
            progress_callback("extracting", 100, "Audio extracted")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "no_warnings": True,
        # yt-dlp's default progress bar writes "[download] ... ETA ..." to
        # stdout without a trailing newline, which collides with our logger's
        # INFO lines. Progress is already reported through progress_hooks (and
        # surfaced to the UI via the job dict), so suppress the stdout bar.
        "noprogress": True,
        # Fix Windows encoding issues with non-ASCII characters
        "encoding": "utf-8",
        # Use multiple clients to avoid blocks
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android", "tv"],
            },
        },
        "progress_hooks": [_progress_hook],
        "postprocessor_hooks": [_pp_hook],
    }

    # Provide ffmpeg location if not in PATH (auto-download if missing)
    try:
        from ffmpeg_setup import ensure_ffmpeg
        ffmpeg_path = ensure_ffmpeg()
    except RuntimeError:
        from ffmpeg_setup import find_ffmpeg
        ffmpeg_path = find_ffmpeg()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_path).parent)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title") if isinstance(info, dict) else None
        if "requested_downloads" in info and info["requested_downloads"]:
            result = info["requested_downloads"][0]["filepath"]
        else:
            filename = ydl.prepare_filename(info)
            base = Path(filename).with_suffix("")
            result = str(base) + ".mp3"
        # Store a persistent copy in the project cache for future requests
        try:
            shutil.copy2(result, cache_path)
        except Exception:
            pass
        _save_cache_title(cache_path, title)
        return AudioDownload(path=result, title=title)


def download_audio(url: str, output_dir: Optional[str] = None, progress_callback=None) -> str:
    """
    Download audio from a YouTube URL as MP3.

    Args:
        url: YouTube video URL
        output_dir: Directory to save the file (default: temp dir)
        progress_callback: Optional callback(stage, percent, message)

    Returns:
        Path to the downloaded audio file
    """
    return download_audio_with_info(
        url, output_dir=output_dir, progress_callback=progress_callback
    ).path
