"""
Locate ffmpeg, downloading a local copy on Windows if it's missing.
"""

import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).parent
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def find_ffmpeg() -> Optional[str]:
    """Find ffmpeg executable. Returns path or None."""
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    for pattern in ["ffmpeg-*/bin/ffmpeg.exe", "ffmpeg-*/bin/ffmpeg"]:
        matches = list(PROJECT_DIR.glob(pattern))
        if matches:
            return str(matches[0])

    return None


def _download_ffmpeg() -> str:
    """Download and extract the latest gyan.dev essentials build into the
    project directory. Returns the path to ffmpeg.exe."""
    zip_path = PROJECT_DIR / "ffmpeg-release-essentials.zip"
    try:
        print(f"ffmpeg not found — downloading from {FFMPEG_ZIP_URL} ...")

        def _progress(block_num, block_size, total_size):
            if total_size > 0:
                pct = min(100, int(block_num * block_size * 100 / total_size))
                print(f"\rDownloading ffmpeg... {pct}%", end="", flush=True)

        urllib.request.urlretrieve(FFMPEG_ZIP_URL, zip_path, _progress)
        print()
        print("Extracting ffmpeg...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(PROJECT_DIR)
    finally:
        if zip_path.exists():
            zip_path.unlink()

    for pattern in ["ffmpeg-*/bin/ffmpeg.exe", "ffmpeg-*/bin/ffmpeg"]:
        matches = list(PROJECT_DIR.glob(pattern))
        if matches:
            return str(matches[0])

    raise RuntimeError("ffmpeg download succeeded but executable not found after extraction.")


def ensure_ffmpeg() -> str:
    """Return the path to ffmpeg, downloading a local copy if needed."""
    path = find_ffmpeg()
    if path:
        return path
    try:
        return _download_ffmpeg()
    except Exception as e:
        raise RuntimeError(
            f"ffmpeg not found and automatic download failed ({e}). "
            "Please install ffmpeg or place a build in the project directory."
        ) from e
