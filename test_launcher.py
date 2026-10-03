"""Regression test: run_server.bat must launch console python, not pythonw.

pythonw has no stdout when detached via `start`, and uvicorn crashes on
startup without it - the server then dies instantly and silently.
"""
from pathlib import Path


def _bat_text():
    return Path(__file__).with_name("run_server.bat").read_text()


def test_launcher_uses_console_python():
    text = _bat_text().lower()
    assert "pythonw server.py" not in text
    assert "pythonw.exe" not in text
    assert "python server.py" in text


def test_launcher_passes_args_through():
    assert "%*" in _bat_text()
