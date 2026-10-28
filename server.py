"""
FastAPI server for lrc-sync web UI.

Usage:
    python server.py [--host 127.0.0.1] [--port 8000]
"""
import argparse
import logging
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

import aligner
from aligner import align
from downloader import download_audio, download_audio_with_info
from lrclib import publish_lrc

import threading
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from logger import log as _log
from logger import JobPollFilter as _JobPollFilter
JobPollFilter = _JobPollFilter

app = FastAPI(title="lrc-sync", description="Sync lyrics with audio to create LRC files")

# All-model pre-download status (for the "download all models" UI button)
_MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v3-turbo",
                "tiny.en", "base.en", "small.en", "medium.en"]
_model_dl_lock = threading.Lock()
_model_dl = {
    "running": False, "current": None, "downloaded": [], "errors": {},
    "done": False, "total": len(_MODEL_SIZES),
}


_JOB_POLL_PATH_RE = re.compile(r"^/api/jobs/[^/]+$")


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Disable browser caching so UI updates always take effect immediately."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        path = request.url.path
        is_job_poll = (
            request.method == "GET"
            and _JOB_POLL_PATH_RE.match(path) is not None
            and response.status_code == 200
        )
        if DEBUG and path not in ("/api/lookup", "/api/publish", "/api/search") and not is_job_poll:
            _log("INFO", f"{request.method} {path} -> {response.status_code}")
        return response


app.add_middleware(NoCacheMiddleware)

# In-memory job store: job_id -> {stage, percent, message, done, lrc, error}
jobs: dict = {}
jobs_lock = threading.Lock()

# Word timestamps kept separate so job polls stay small:
# job_id -> [{"word", "start", "end"}, ...]
job_words: dict = {}

# Per-character sync JSON per finished job
job_sync: dict = {}

# Always produce words.json / output_sync.json outputs
CHARACTER_LEVEL = True

DEBUG = False


# Web UI HF-token prompt coordination
_ui_token = {"evt": None, "token": "", "model": None}
_current_job_id = None


def _ui_token_provider(model_name):
    global _ui_token, _current_job_id
    if _ui_token["evt"] is not None:
        _ui_token["evt"].set()
        _ui_token["evt"] = None
    evt = threading.Event()
    _ui_token = {"evt": evt, "token": "", "model": model_name}
    with jobs_lock:
        job = jobs.get(_current_job_id)
        if job is not None:
            job["need_token"] = model_name
    with _model_dl_lock:
        _model_dl["need_token"] = model_name
    _log("INFO", f"Waiting for HF token via web UI (model={model_name})...")
    evt.wait(timeout=900)
    with jobs_lock:
        job = jobs.get(_current_job_id)
        if job is not None:
            job.pop("need_token", None)
    with _model_dl_lock:
        _model_dl.pop("need_token", None)
    token = _ui_token.get("token", "")
    _ui_token = {"evt": None, "token": "", "model": None}
    return token

# Cancel events per running job
job_cancel: dict = {}

_job_log: dict = {}


def _update_job(job_id: str, stage: str, percent: int, message: str):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update({
                "stage": stage,
                "percent": percent,
                "message": message,
            })
    if DEBUG and _job_log.get(job_id) != (stage, percent // 10):
        _job_log[job_id] = (stage, percent // 10)
        _log("INFO", f"/api/jobs {job_id} {stage} {percent}% {message}")


def sync_filename(title: Optional[str] = None, fallback: Optional[str] = None) -> str:
    """Filename for the sync JSON download: `<shortened title>_sync.json`.

    `title` is the YouTube title. `fallback` is an uploaded audio filename,
    used when there is no title to work from.
    """
    from downloader import sanitize_title

    if not title and fallback:
        title = Path(fallback).stem
    return sanitize_title(title) + "_sync.json"


def _run_job(
    job_id: str,
    audio_path: str = None,
    url: str = None,
    lyrics: str = "",
    model: str = "medium",
    language: str = None,
    offset: float = 0.0,
    cleanup_paths: list = None,
    temperature: float = 0.0,
    beam_size: int = 5,
    best_of: int = 5,
    separate_vocals: bool = False,
    similarity_mode: str = "bigram",
    accept_threshold: float = 0.4,
    source_filename: str = None,
    method: str = "whisper",
):
    """Background worker: download (if URL) + align, storing progress."""
    global _current_job_id
    _current_job_id = job_id

    def cb(stage, percent, message):
        if job_cancel.get(job_id) and job_cancel[job_id].is_set():
            raise RuntimeError("Cancelled")
        if stage == "detecting_language" and "Detected" in message:
            try:
                lang = message.rsplit(":", 1)[1].split("(")[0].strip()
                if lang:
                    with jobs_lock:
                        if job_id in jobs:
                            jobs[job_id]["detected_language"] = lang
            except IndexError:
                pass
        _update_job(job_id, stage, percent, message)

    title = None
    try:
        if job_cancel.get(job_id) and job_cancel[job_id].is_set():
            raise RuntimeError("Cancelled")
        path = audio_path
        if url:
            cb("downloading", 0, "Downloading...")
            downloaded = download_audio_with_info(url, progress_callback=cb)
            path = downloaded.path
            title = downloaded.title
            if cleanup_paths is not None:
                cleanup_paths.append(path)

        result = align(
            audio_path=path,
            lyrics_text=lyrics,
            model_size=model,
            language=language,
            offset=offset,
            progress_callback=cb,
            temperature=temperature,
            beam_size=beam_size,
            best_of=best_of,
            separate_vocals=separate_vocals,
            similarity_mode=similarity_mode,
            accept_threshold=accept_threshold,
            method=method,
        )
        with jobs_lock:
            jobs[job_id].update({
                "done": True,
                "lrc": result.lrc_text,
                "warnings": result.warnings,
                "detected_language": getattr(result, "detected_language", None),
                # Surfaced to the UI: names the sync download and pre-fills
                # the LRCLIB duration field.
                "duration": getattr(result, "duration", None),
                "sync_filename": sync_filename(title, fallback=source_filename),
                "stage": "done",
                "percent": 100,
                "message": "Done!",
            })
        with jobs_lock:
            if CHARACTER_LEVEL:
                job_words[job_id] = [
                    {"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3),
                     **({"confidence": round(w.confidence, 3)} if w.confidence is not None else {})}
                    for w in result.words
                ]
                job_sync[job_id] = result.sync_text
    except Exception as e:
        cancelled = job_cancel.get(job_id) is not None and job_cancel[job_id].is_set()
        with jobs_lock:
            if cancelled or str(e) == "Cancelled":
                jobs[job_id].update({
                    "done": True,
                    "stage": "cancelled",
                    "message": "Cancelled",
                    "error": None,
                })
            else:
                jobs[job_id].update({
                    "done": True,
                    "error": str(e),
                    "stage": "error",
                    "message": f"Error: {e}",
                })
    finally:
        for p in (cleanup_paths or []):
            Path(p).unlink(missing_ok=True)


@app.post("/api/jobs")
async def create_job(
    audio: UploadFile = File(None),
    url: str = Form(None),
    lyrics: str = Form(...),
    model: str = Form("medium"),
    language: str = Form(None),
    offset: float = Form(0.0),
    temperature: float = Form(0.0),
    beam_size: int = Form(5),
    best_of: int = Form(5),
    separate_vocals: bool = Form(False),
    similarity: str = Form("bigram"),
    accept_threshold: float = Form(0.4),
    method: str = Form("whisper"),
    hf_token: str = Form(None),
):
    """Start an alignment job. Returns {"job_id": ...} immediately."""
    if (audio is None or not audio.filename) and not url:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=400,
            content={"error": "Provide an audio file or a YouTube URL."},
        )

    if hf_token and hf_token.strip():
        import os as _os
        _os.environ["HF_TOKEN"] = hf_token.strip()

    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {
            "stage": "queued", "percent": 0,
            "message": "Queued...", "done": False,
            "lrc": None, "error": None, "warnings": [],
        }
        job_cancel[job_id] = threading.Event()

    import aligner
    aligner.TOKEN_PROVIDER = _ui_token_provider

    cleanup_paths = []
    audio_path = None
    if audio is not None and audio.filename:
        suffix = Path(audio.filename).suffix
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix,
            dir=tempfile.gettempdir(),
        ) as tmp:
            tmp.write(await audio.read())
            audio_path = tmp.name
        cleanup_paths.append(audio_path)

    thread = threading.Thread(
        target=_run_job,
        kwargs={
            "job_id": job_id,
            "audio_path": audio_path,
            "url": url,
            "lyrics": lyrics,
            "model": model,
            "language": language,
            "offset": offset,
            "temperature": temperature,
            "beam_size": beam_size,
            "best_of": best_of,
            "separate_vocals": separate_vocals,
            "similarity_mode": similarity,
            "accept_threshold": accept_threshold,
            "cleanup_paths": cleanup_paths,
            "source_filename": audio.filename if audio is not None else None,
            "method": method,
        },
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Poll job progress. Returns stage/percent/message, plus lrc when done."""
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "Unknown job"})
        return dict(job, character_level=CHARACTER_LEVEL)


@app.post("/api/token")
async def submit_token(token: str = Form(...)):
    global _ui_token
    if _ui_token.get("evt") is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "No pending token request"})
    _ui_token["token"] = (token or "").strip()
    _ui_token["evt"].set()
    return {"status": "ok"}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "Unknown job"})
        if job.get("done"):
            return {"status": "already_done"}
        if job_id in job_cancel:
            job_cancel[job_id].set()
        job.update({"stage": "cancelled", "message": "Cancelling..."})
    return {"status": "ok"}


@app.get("/api/jobs/{job_id}/sync")
async def get_job_sync(job_id: str):
    """Return per-character sync JSON for a finished job."""
    from fastapi.responses import PlainTextResponse, JSONResponse
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return JSONResponse(status_code=404, content={"error": "Unknown job"})
        if job.get("error"):
            return JSONResponse(status_code=409, content={"error": f"Job failed: {job['error']}"})
        if not job.get("done"):
            return JSONResponse(status_code=409, content={"error": "Job not done yet"})
        if not CHARACTER_LEVEL:
            return JSONResponse(status_code=404, content={"error": "Character-level output disabled"})
        text = job_sync.get(job_id)
        if text is None:
            return JSONResponse(status_code=404, content={"error": "No sync data"})
        return PlainTextResponse(text, media_type="application/json")


@app.get("/api/jobs/{job_id}/words")
async def get_job_words(job_id: str):
    """Return word-level timestamps for a finished job as {"words": [...]}."""
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "Unknown job"})
        if job.get("error"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=409, content={"error": f"Job failed: {job['error']}"})
        if not job.get("done"):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=409, content={"error": "Job not done yet"})
        if not CHARACTER_LEVEL:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "Character-level output disabled"})
        return {"words": job_words.get(job_id, [])}


@app.post("/api/align", response_class=PlainTextResponse)
async def align_endpoint(
    audio: UploadFile = File(...),
    lyrics: str = Form(...),
    model: str = Form("medium"),
    language: str = Form(None),
    offset: float = Form(0.0),
    separate_vocals: bool = Form(False),
    method: str = Form("whisper"),
):
    """Upload audio + lyrics, return synced LRC text."""
    # Save uploaded audio to temp file
    suffix = Path(audio.filename or "audio.mp3").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        audio_path = tmp.name

    try:
        result = align(
            audio_path=audio_path,
            lyrics_text=lyrics,
            model_size=model,
            language=language,
            offset=offset,
            separate_vocals=separate_vocals,
            method=method,
        )
        return result.lrc_text
    finally:
        Path(audio_path).unlink(missing_ok=True)


@app.post("/api/youtube", response_class=PlainTextResponse)
async def youtube_endpoint(
    url: str = Form(...),
    lyrics: str = Form(...),
    model: str = Form("medium"),
    language: str = Form(None),
    offset: float = Form(0.0),
    separate_vocals: bool = Form(False),
    method: str = Form("whisper"),
):
    """Download from YouTube, then align with lyrics. Returns LRC text."""
    import tempfile

    # Download audio to temp file
    audio_path = download_audio(url, output_dir=tempfile.gettempdir())

    try:
        result = align(
            audio_path=audio_path,
            lyrics_text=lyrics,
            model_size=model,
            language=language,
            offset=offset,
            separate_vocals=separate_vocals,
            method=method,
        )
        return result.lrc_text
    finally:
        Path(audio_path).unlink(missing_ok=True)


@app.post("/api/models/download-all")
async def download_all_models():
    """Download (and briefly load) every model size ahead of time."""
    with _model_dl_lock:
        if _model_dl["running"]:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=409, content={"error": "Model download already running"})
        _model_dl.update({"running": True, "current": None, "downloaded": [], "errors": {}, "done": False})

    def _worker():
        aligner.TOKEN_PROVIDER = _ui_token_provider
        for size in _MODEL_SIZES:
            with _model_dl_lock:
                _model_dl["current"] = size
            try:
                m = aligner._load_whisper_model(size)
                del m
                with _model_dl_lock:
                    _model_dl["downloaded"].append(size)
            except Exception as e:
                with _model_dl_lock:
                    _model_dl["errors"][size] = str(e)
        with _model_dl_lock:
            _model_dl.update({"running": False, "current": None, "done": True})

    threading.Thread(target=_worker, daemon=True).start()
    return {"status": "started"}


@app.get("/api/models/download-status")
async def download_status():
    with _model_dl_lock:
        return dict(_model_dl)


@app.get("/api/health")
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/paxsenix")
async def paxsenix_endpoint(id: str):
    """Fetch synced lyrics from Paxsenix (Apple Music TTML).

    Line-timed tracks return {"timing": "line", "lrc": ...};
    word-timed tracks additionally return "syncJson" in output_sync.json shape.
    """
    from fastapi.responses import JSONResponse
    from paxsenix import extract_apple_id, fetch_ttml, parse_ttml, to_lrc, to_sync_json

    try:
        track_id = extract_apple_id(id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    try:
        parsed = parse_ttml(fetch_ttml(track_id))
    except (RuntimeError, ValueError) as e:
        return JSONResponse(status_code=502, content={"error": str(e)})

    result = {
        "timing": parsed["timing"],
        "trackId": track_id,
        "lrc": to_lrc(parsed),
    }
    if parsed["timing"] == "word":
        result["syncJson"] = to_sync_json(parsed)
    return result


@app.get("/api/lookup")
async def lookup_endpoint(artist: str = None, track: str = None, duration: float = None, id: int = None):
    """Retry ID lookup without re-publishing. Returns {"id": ...} or 404."""
    from fastapi.responses import JSONResponse
    from lrclib import get_by_id, lookup_record

    if DEBUG:
        _log("INFO", f"/api/lookup artist={artist!r} track={track!r} duration={duration!r} id={id!r}")
    try:
        if id is not None:
            record = get_by_id(id)
        elif artist and track and duration:
            record = lookup_record(artist, track, duration)
        else:
            return JSONResponse(status_code=400, content={"error": "Provide id, or artist + track + duration"})
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    if record is None:
        return JSONResponse(status_code=404, content={"error": "Not found on LRCLIB yet"})
    return {"id": record.get("id")}


@app.post("/api/publish")
async def publish_endpoint(
    track: str = Form(...),
    artist: str = Form(...),
    duration: float = Form(...),
    lrc: str = Form(...),
    album: str = Form(None),
):
    """Publish synced LRC to LRCLIB. Returns {"status", "id"}."""
    from lrclib import lookup_record, validate_lrc

    if DEBUG:
        _log("INFO", f"/api/publish track={track!r} artist={artist!r} duration={duration!r} album={album!r} lrc_len={len(lrc)}")
    try:
        problems = validate_lrc(lrc)
        if problems["duplicates"] or problems["out_of_order"]:
            from fastapi.responses import JSONResponse
            msg = "LRC timestamps must be strictly increasing"
            return JSONResponse(status_code=400, content={
                "status": "error", "error": msg, "message": msg,
                "duplicates": problems["duplicates"],
                "out_of_order": problems["out_of_order"],
            })
        result = publish_lrc(
            track_name=track,
            artist_name=artist,
            duration=duration,
            lrc_text=lrc,
            album_name=album,
            progress_callback=lambda nonce, hps=0: (
                _log("INFO", f"/api/publish challenge {hps:.0f} H/s")
            ),
        )
        entry_id = result.get("id")
        if entry_id is None:
            # Empty-body success: resolve the id with a lookup
            try:
                record = lookup_record(artist, track, duration)
                if record:
                    entry_id = record.get("id")
            except RuntimeError:
                pass
        if DEBUG:
            _log("WARN" if entry_id is None else "INFO", f"/api/publish verification result={result!r} entry_id={entry_id!r}")
        if entry_id is None:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=202, content={
                "status": "submitted", "id": None,
                "reason": "not-yet-visible", "response": result,
            })
        return {"status": "published", "id": entry_id, "response": result}
    except (ValueError, RuntimeError) as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})


@app.get("/api/search")
async def search_endpoint(artist_name: str, track_name: str):
    """Search LRCLIB for matching tracks. Returns the raw result list."""
    from fastapi.responses import JSONResponse
    from lrclib import search_records

    if DEBUG:
        _log("INFO", f"/api/search artist_name={artist_name!r} track_name={track_name!r}")
    try:
        results = search_records(artist_name, track_name)
        if DEBUG:
            _log("WARN" if not results else "INFO", f"/api/search -> {len(results)} result(s)")
        return results
    except RuntimeError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


# Serve static files (web UI)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


def main():
    parser = argparse.ArgumentParser(description="lrc-sync web server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open the web UI in a browser",
    )
    parser.add_argument(
        "--characterlevel", action="store_true",
        help="Enable word/character-level JSON endpoints and UI buttons",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable verbose debug logs",
    )
    # (--silent removed: console output is always on now)
    args = parser.parse_args()

    global CHARACTER_LEVEL, DEBUG
    CHARACTER_LEVEL = bool(args.characterlevel)
    DEBUG = bool(args.debug)

    if not args.no_browser:
        import threading
        import time
        import webbrowser

        url = f"http://{args.host}:{args.port}"

        def _open():
            time.sleep(1.5)  # let the server finish starting
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()
        _log("INFO", f"Opening {url} in your browser...")

    # Route any third-party/library logs through the same colored formatter.
    from logger import UvicornDefaultFormatter
    _root = logging.getLogger()
    if not _root.handlers:
        _h = logging.StreamHandler()
        _h.setFormatter(UvicornDefaultFormatter())
        _root.addHandler(_h)
        _root.setLevel(logging.INFO)

    import uvicorn

    # On Windows uvicorn defaults to ProactorEventLoop, whose accept path closes
    # the listening socket when a client resets before AcceptEx completes
    # (python/cpython#93821). Use a SelectorEventLoop instead: it survives
    # per-connection resets instead of killing the server. See eventloop.py.
    loop = "eventloop:selector_loop_factory" if sys.platform == "win32" else "auto"
    import copy
    from uvicorn.config import LOGGING_CONFIG
    # Patching loggers here is a no-op: uvicorn.run reinstalls handlers via dictConfig afterwards.
    log_config = copy.deepcopy(LOGGING_CONFIG)
    log_config["formatters"]["default"] = {"()": "logger.UvicornDefaultFormatter"}
    log_config["formatters"]["access"] = {"()": "logger.UvicornAccessFormatter"}
    log_config["filters"] = {"job_poll": {"()": "logger.JobPollFilter"}}
    log_config["handlers"]["access"]["filters"] = ["job_poll"]
    uvicorn.run(app, host=args.host, port=args.port, log_level="debug" if DEBUG else "info", access_log=True, loop=loop, log_config=log_config)


if __name__ == "__main__":
    main()
