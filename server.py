"""
FastAPI server for lrc-sync web UI.

Usage:
    python server.py [--host 127.0.0.1] [--port 8000]
"""
import argparse
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from aligner import align
from downloader import download_audio
from lrclib import publish_lrc

import threading
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

app = FastAPI(title="lrc-sync", description="Sync lyrics with audio to create LRC files")


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Disable browser caching so UI updates always take effect immediately."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoCacheMiddleware)

# In-memory job store: job_id -> {stage, percent, message, done, lrc, error}
jobs: dict = {}
jobs_lock = threading.Lock()


def _update_job(job_id: str, stage: str, percent: int, message: str):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update({
                "stage": stage,
                "percent": percent,
                "message": message,
            })


def _run_job(
    job_id: str,
    audio_path: str = None,
    url: str = None,
    lyrics: str = "",
    model: str = "small",
    language: str = None,
    offset: float = 0.0,
    cleanup_paths: list = None,
):
    """Background worker: download (if URL) + align, storing progress."""
    def cb(stage, percent, message):
        _update_job(job_id, stage, percent, message)

    try:
        path = audio_path
        if url:
            cb("downloading", 0, "Downloading...")
            path = download_audio(url, progress_callback=cb)
            if cleanup_paths is not None:
                cleanup_paths.append(path)

        result = align(
            audio_path=path,
            lyrics_text=lyrics,
            model_size=model,
            language=language,
            offset=offset,
            progress_callback=cb,
        )
        with jobs_lock:
            jobs[job_id].update({
                "done": True,
                "lrc": result.lrc_text,
                "warnings": result.warnings,
                "stage": "done",
                "percent": 100,
                "message": "Done!",
            })
    except Exception as e:
        with jobs_lock:
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
    model: str = Form("small"),
    language: str = Form(None),
    offset: float = Form(0.0),
):
    """Start an alignment job. Returns {"job_id": ...} immediately."""
    if (audio is None or not audio.filename) and not url:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=400,
            content={"error": "Provide an audio file or a YouTube URL."},
        )

    job_id = uuid.uuid4().hex[:12]
    with jobs_lock:
        jobs[job_id] = {
            "stage": "queued", "percent": 0,
            "message": "Queued...", "done": False,
            "lrc": None, "error": None, "warnings": [],
        }

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
            "cleanup_paths": cleanup_paths,
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
        return dict(job)


@app.post("/api/align", response_class=PlainTextResponse)
async def align_endpoint(
    audio: UploadFile = File(...),
    lyrics: str = Form(...),
    model: str = Form("small"),
    language: str = Form(None),
    offset: float = Form(0.0),
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
        )
        return result.lrc_text
    finally:
        Path(audio_path).unlink(missing_ok=True)


@app.post("/api/youtube", response_class=PlainTextResponse)
async def youtube_endpoint(
    url: str = Form(...),
    lyrics: str = Form(...),
    model: str = Form("small"),
    language: str = Form(None),
    offset: float = Form(0.0),
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
        )
        return result.lrc_text
    finally:
        Path(audio_path).unlink(missing_ok=True)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/publish")
async def publish_endpoint(
    track: str = Form(...),
    artist: str = Form(...),
    duration: float = Form(...),
    lrc: str = Form(...),
    album: str = Form(None),
):
    """Publish synced LRC to LRCLIB."""
    try:
        result = publish_lrc(
            track_name=track,
            artist_name=artist,
            duration=duration,
            lrc_text=lrc,
            album_name=album,
        )
        return {"status": "published", "response": result}
    except (ValueError, RuntimeError) as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})


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
    args = parser.parse_args()

    if not args.no_browser:
        import threading
        import time
        import webbrowser

        url = f"http://{args.host}:{args.port}"

        def _open():
            time.sleep(1.5)  # let the server finish starting
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()
        print(f"Opening {url} in your browser...")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
