"""Shared console logger — one format, color, and style for every log line.

Format: ``[LEVEL] message`` with ANSI color (green INFO, yellow WARN,
red ERROR/ISSUES). Data output (LRC text, JSON, record details) stays plain
and must NOT go through here.
"""

from copy import copy as _copy
import logging
import os
import re
import sys
import threading

GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
CYAN = "\x1b[36m"
RESET = "\x1b[0m"

_COLORS = {"INFO": GREEN, "WARN": YELLOW, "ERROR": RED, "ISSUES": RED, "DEBUG": CYAN}

_LEVEL_MAP = {"WARNING": "WARN", "CRITICAL": "ERROR"}


def _level_prefix(levelname: str) -> str:
    """Render a level as the shared colored ``[LEVEL]`` prefix."""
    level = _LEVEL_MAP.get(levelname, levelname)
    return f"{_COLORS.get(level, GREEN)}[{level}]{RESET}"


def _enable_windows_ansi():
    if os.name != "nt":
        return
    try:
        import ctypes
        _kernel32 = ctypes.windll.kernel32
        for _handle in (-11, -12):
            _mode = ctypes.c_ulong()
            if _kernel32.GetConsoleMode(_kernel32.GetStdHandle(_handle), ctypes.byref(_mode)):
                _kernel32.SetConsoleMode(_kernel32.GetStdHandle(_handle), _mode.value | 0x0004)
    except Exception:
        try:
            os.system("")
        except Exception:
            pass


_enable_windows_ansi()


# Serializes console writes so a logger INFO line can never be appended to an
# in-flight progress line (e.g. yt-dlp/ffmpeg) emitted by another thread.
_LOG_LOCK = threading.Lock()


def log(kind, msg, file=sys.stdout, end="\n"):
    """Print one ``[KIND] msg`` line in the shared color/style."""
    color = _COLORS.get(kind, GREEN)
    text = str(msg)
    prefix = ""
    if text.startswith("\r"):
        prefix, text = "\r", text[1:]
    with _LOG_LOCK:
        print(f"{prefix}{color}[{kind}]{RESET} {text}", file=file, flush=True, end=end)


class ColorFormatter(logging.Formatter):
    """logging.Formatter that renders ``[LEVEL] message`` in the shared style."""

    def format(self, record):
        original_levelname = record.levelname
        record.levelname = _level_prefix(original_levelname)
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


# uvicorn-aware formatters: keep uvicorn's arg parsing (access logs) but render
# the level as a colored ``[LEVEL]`` prefix to match the rest of the app.
try:
    from uvicorn.logging import ColourizedFormatter as _UvColourized
    from uvicorn.logging import AccessFormatter as _UvAccess
except Exception:  # pragma: no cover - uvicorn not installed
    _UvColourized = logging.Formatter
    _UvAccess = logging.Formatter


class UvicornDefaultFormatter(_UvColourized):
    def __init__(self, fmt=None, datefmt=None, style="%", use_colors=None, **kw):
        if fmt is None:
            fmt = "%(levelprefix)s %(message)s"
        super().__init__(fmt=fmt, datefmt=datefmt, style=style, use_colors=True)

    def formatMessage(self, record):
        recordcopy = _copy(record)
        if "color_message" in recordcopy.__dict__:
            recordcopy.msg = recordcopy.__dict__["color_message"]
            recordcopy.__dict__["message"] = recordcopy.getMessage()
        recordcopy.__dict__["levelprefix"] = _level_prefix(recordcopy.levelname)
        return logging.Formatter.formatMessage(self, recordcopy)


class UvicornAccessFormatter(_UvAccess):
    def __init__(self, fmt=None, datefmt=None, style="%", use_colors=None, **kw):
        if fmt is None:
            fmt = '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
        super().__init__(fmt=fmt, datefmt=datefmt, style=style, use_colors=True)

    def formatMessage(self, record):
        recordcopy = _copy(record)
        (
            client_addr,
            method,
            full_path,
            http_version,
            status_code,
        ) = recordcopy.args
        status_code = self.get_status_code(int(status_code))
        request_line = f"{method} {full_path} HTTP/{http_version}"
        recordcopy.__dict__.update(
            {
                "client_addr": client_addr,
                "request_line": request_line,
                "status_code": status_code,
            }
        )
        if "color_message" in recordcopy.__dict__:
            recordcopy.msg = recordcopy.__dict__["color_message"]
            recordcopy.__dict__["message"] = recordcopy.getMessage()
        recordcopy.__dict__["levelprefix"] = _level_prefix(recordcopy.levelname)
        return logging.Formatter.formatMessage(self, recordcopy)

# Filter successful polling of GET /api/jobs/{id} from uvicorn's access log.
# The frontend polls this endpoint frequently; logging every 200 floods output.
# Errors/warnings (non-200 or other paths) are kept.
_JOB_POLL_PATH_RE = re.compile(r"^/api/jobs/[^/?#]+$")


class JobPollFilter(logging.Filter):
    def filter(self, record):
        method = None
        path = None
        status = None
        args = getattr(record, "args", None)
        if isinstance(args, (tuple, list)) and len(args) >= 5:
            try:
                method = str(args[1])
                path = str(args[2])
                status = int(args[4])
            except (TypeError, ValueError, IndexError):
                method = path = status = None
        if method is None or path is None or status is None:
            try:
                msg = record.getMessage()
            except Exception:
                msg = str(getattr(record, "msg", ""))
            m = re.search(r'"([A-Z]+)\s+(\S+)\s+HTTP/[^"]*"\s+(\d{3})', msg)
            if m:
                method, path, status = m.group(1), m.group(2), int(m.group(3))
        if method == "GET" and status == 200 and path is not None:
            clean = path.split("?", 1)[0].split("#", 1)[0]
            if _JOB_POLL_PATH_RE.match(clean):
                return False
        return True


job_poll_filter = JobPollFilter()
