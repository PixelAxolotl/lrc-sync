"""
YouTube audio downloader using yt-dlp.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).parent
DEFAULT_TEMP_DIR = PROJECT_DIR / "temp"
AUDIO_CACHE_DIR = PROJECT_DIR / "cache_audio"


def _find_ffmpeg() -> Optional[str]:
    """Find ffmpeg executable. Returns path or None."""
    from ffmpeg_setup import find_ffmpeg
    return find_ffmpeg()


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
    import yt_dlp
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
        return str(out)

    outtmpl = str(Path(output_dir) / "%(title)s.%(ext)s")

    def _progress_hook(d):
        if progress_callback:
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total > 0:
                    pct = min(100, int((downloaded / total) * 100))
                    progress_callback("downloading", pct, f"Downloading... {pct}%")
            elif d["status"] == "finished":
                progress_callback("downloading", 100, "Download complete, converting...")

    def _pp_hook(d):
        if progress_callback:
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
        ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_path).parent)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
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
        return result
