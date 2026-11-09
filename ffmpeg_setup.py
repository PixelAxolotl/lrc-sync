"""
Locate ffmpeg, downloading a local copy on Windows if it's missing.
"""

import hashlib
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from logger import log

PROJECT_DIR = Path(__file__).parent
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_SHA256_URL = FFMPEG_ZIP_URL + ".sha256"


def _expected_sha256() -> Optional[str]:
    """The build's published SHA-256, or None when it cannot be retrieved."""
    try:
        with urllib.request.urlopen(FFMPEG_SHA256_URL, timeout=30) as resp:
            text = resp.read().decode("utf-8", "replace").strip()
    except Exception as e:
        log("WARN", f"Could not fetch the ffmpeg checksum ({e}); skipping verification.")
        return None
    token = text.split()[0].lower() if text else ""
    return token if re.fullmatch(r"[0-9a-f]{64}", token) else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract an archive, refusing members that escape `target_dir`."""
    root = target_dir.resolve()
    for info in zf.infolist():
        member = (root / info.filename).resolve()
        if not (member == root or member.is_relative_to(root)):
            raise RuntimeError(f"Refusing unsafe archive member: {info.filename}")
    zf.extractall(root)


def find_ffmpeg() -> Optional[str]:
    """Find ffmpeg executable. Returns path or None."""
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        return ffmpeg_in_path

    for pattern in ("ffmpeg-*/bin/ffmpeg.exe", "ffmpeg-*/bin/ffmpeg"):
        match = next(PROJECT_DIR.glob(pattern), None)
        if match:
            return str(match)

    return None


def _download_ffmpeg() -> str:
    """Download and extract the latest gyan.dev essentials build into the
    project directory. Returns the path to ffmpeg.exe."""
    zip_path = PROJECT_DIR / "ffmpeg-release-essentials.zip"
    try:
        log("INFO", f"ffmpeg not found — downloading from {FFMPEG_ZIP_URL} ...")

        def _progress(block_num, block_size, total_size):
            if total_size > 0:
                pct = min(100, int(block_num * block_size * 100 / total_size))
                log("INFO", f"\rDownloading ffmpeg... {pct}%", end="")

        urllib.request.urlretrieve(FFMPEG_ZIP_URL, zip_path, _progress)
        print()
        expected = _expected_sha256()
        if expected:
            actual = _sha256_file(zip_path)
            if actual != expected:
                raise RuntimeError(
                    f"ffmpeg archive checksum mismatch (expected {expected}, got {actual})"
                )
            log("INFO", "ffmpeg archive checksum verified.")
        log("INFO", "Extracting ffmpeg...")
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, PROJECT_DIR)
    finally:
        if zip_path.exists():
            zip_path.unlink()

    for pattern in ("ffmpeg-*/bin/ffmpeg.exe", "ffmpeg-*/bin/ffmpeg"):
        match = next(PROJECT_DIR.glob(pattern), None)
        if match:
            return str(match)

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
