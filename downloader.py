"""
YouTube audio downloader using yt-dlp.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional


def _find_ffmpeg() -> Optional[str]:
    """Find ffmpeg executable. Returns path or None."""
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

    if output_dir is None:
        output_dir = tempfile.gettempdir()

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

    # Provide ffmpeg location if not in PATH
    ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_path).parent)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # yt-dlp returns the actual file path in the info dict
        if "requested_downloads" in info and info["requested_downloads"]:
            return info["requested_downloads"][0]["filepath"]
        # Fallback: construct the path
        filename = ydl.prepare_filename(info)
        # The postprocessor changes the extension to .mp3
        base = Path(filename).with_suffix("")
        return str(base) + ".mp3"
