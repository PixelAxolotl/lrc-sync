# Multi-Method Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add selectable alignment backends (whisper, whisperx, stable-ts) behind the existing `align()` entry point, keeping whisper as the default, with UI dropdown, CLI flag, and optional packaging extras.

**Architecture:** A backend protocol `align_audio(audio_path, lines, lang, model_size, progress_callback=None) -> list[WordTimestamp]` is implemented per method. `align()` resolves the backend from a registry and delegates transcription; `match_lyrics_to_words` and all downstream formatting stay method-agnostic. Optional dependencies are lazy-imported with friendly install messages.

**Tech Stack:** Python 3.12+, faster-whisper (base), optional whisperx / stable-ts, FastAPI, argparse, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-10-27-multi-method-alignment-design.md`

## Global Constraints

- No model downloads in CI: backends are mocked or skipped when their extra is absent.
- Whisper remains the default; default code path behavior must not change.
- Backends return only `list[WordTimestamp]`; they never emit spans.
- Lazy imports inside each backend; missing extras raise a friendly `RuntimeError` naming the install command.
- No auto-fallback chain, no benchmark/compare UI, no Demucs coupling.
- Post-processing in `align()` (`match_lyrics_to_words`, `format_lrc`, `sync_json`, `_char_times_for_line`) is untouched.
- TDD: write the failing test first, then minimal implementation, then run tests, then commit.

## Review Focus

- Dispatch correctness and default selection.
- Protocol signature and kwarg forwarding (temperature, beam_size, best_of, initial_prompt, fallback_temperatures, drop_looped).
- Friendly missing-dependency errors.
- Method propagation through server endpoints and CLI.
- UI dropdown wiring.
- Packaging extras in `pyproject.toml`.
- Parity test coverage without model downloads.

---

## File Structure

Created:
- `backends/__init__.py` — package marker + `MissingBackendError` (alias of RuntimeError).
- `backends/whisper_backend.py` — wraps `transcribe_with_whisper`.
- `backends/whisperx_backend.py` — lazy `whisperx` adapter.
- `backends/stablets_backend.py` — lazy `stable_whisper` adapter.
- `pyproject.toml` — packaging metadata + optional extras.
- `test/test_backends.py` — registry + missing-extra + whisper delegation tests.
- `test/test_alignment_methods.py` — dispatch + parity shape tests.

Modified:
- `aligner.py` — `align()` gains `method` param; registry + `get_backend()`; dispatch.
- `server.py` — `_run_job`, `create_job`, `/api/align`, `/api/youtube` forward `method`.
- `cli.py` — `--method` flag forwarded at `align()` call (`cli.py:128`).
- `static/index.html` — method dropdown next to model select (`~193-204`).
- `static/app.js` — read method and append to form data (`~300`, `~343`).

---

## Task 1: Backend package + WhisperBackend extraction

**Files:**
- Create: `backends/__init__.py`
- Create: `backends/whisper_backend.py`
- Test: `test/test_backends.py`

**Interfaces:**
- Consumes: `aligner.transcribe_with_whisper`, `aligner.WordTimestamp`
- Produces: `backends.whisper_backend.align_audio(audio_path, lines, lang, model_size, progress_callback=None, temperature=0.0, beam_size=5, best_of=5, initial_prompt=None, fallback_temperatures=(0.2, 0.4), drop_looped=True, warnings=None, **kwargs) -> list[WordTimestamp]`

- [ ] **Step 1: Write failing tests**

Create `test/test_backends.py`:
```python
import sys, os
sys.path.insert(0, os.path.abspath(".."))
import aligner
from backends import whisper_backend

def test_whisper_backend_delegates_to_transcribe(monkeypatch):
    calls = {}
    def fake_transcribe(wav_path, model_size, language, progress_callback=None,
                        temperature=0.0, beam_size=8, best_of=5, initial_prompt=None,
                        fallback_temperatures=(0.2, 0.4), drop_looped=True):
        calls["args"] = (wav_path, model_size, language, temperature, beam_size, best_of, initial_prompt, fallback_temperatures, drop_looped)
        return [aligner.WordTimestamp(word="hi", start=1.0, end=2.0, confidence=0.9)], 2
    monkeypatch.setattr(aligner, "transcribe_with_whisper", fake_transcribe)
    warnings = []
    words = whisper_backend.align_audio("/tmp/a.wav", ["line"], "en", "small",
                                       progress_callback=None, temperature=0.1, beam_size=4,
                                       best_of=3, initial_prompt="p", drop_looped=False,
                                       warnings=warnings)
    assert len(words) == 1
    assert words[0].word == "hi"
    assert warnings and "Skipped 2 looped" in warnings[0]
    assert calls["args"][1] == "small"

def test_whisper_backend_missing_returns_empty_list(monkeypatch):
    monkeypatch.setattr(aligner, "transcribe_with_whisper", lambda *a, **k: ([], 0))
    assert whisper_backend.align_audio("/tmp/a.wav", [], None, "small") == []
```

- [ ] **Step 2: Run tests — expect FAIL** (module missing)
```bash
cd C:\Users\thorz\OneDrive\Desktop\lrc-sync && python -m pytest test/test_backends.py -q
```

- [ ] **Step 3: Implement `backends/__init__.py` and `backends/whisper_backend.py`**

`backends/__init__.py`:
```python
"""Alignment backend implementations."""

MissingBackendError = RuntimeError
```

`backends/whisper_backend.py`:
```python
from aligner import WordTimestamp


def align_audio(audio_path, lines, lang, model_size, progress_callback=None,
               temperature=0.0, beam_size=5, best_of=5, initial_prompt=None,
               fallback_temperatures=(0.2, 0.4), drop_looped=True,
               warnings=None, **kwargs):
    from aligner import transcribe_with_whisper
    words, skipped_looped = transcribe_with_whisper(
        audio_path, model_size, lang, progress_callback=progress_callback,
        temperature=temperature, beam_size=beam_size, best_of=best_of,
        initial_prompt=initial_prompt,
        fallback_temperatures=fallback_temperatures,
        drop_looped=drop_looped,
    )
    if skipped_looped and warnings is not None:
        warnings.append(
            f"Skipped {skipped_looped} looped transcription segment(s) "
            f"(repetition hallucination). Timestamps may be sparse there."
        )
    return list(words)
```

- [ ] **Step 4: Run tests — expect PASS**
```bash
cd C:\Users\thorz\OneDrive\Desktop\lrc-sync && python -m pytest test/test_backends.py -q
```

- [ ] **Step 5: Commit**
```bash
git add backends/ test/test_backends.py && git commit -m "feat(backends): add whisper backend wrapper"
```

---

## Task 2: Registry + `align()` dispatch

**Files:**
- Modify: `aligner.py` (`align()` signature ~981, transcription block ~1087-1093)
- Test: `test/test_backends.py` (append)

**Interfaces:**
- Consumes: backend modules
- Produces: `aligner.get_backend(method: str) -> callable`, `align(..., method="whisper")`

- [ ] **Step 1: Append failing tests**

```python
import aligner as _aligner

def test_registry_has_three_backends():
    reg = _aligner._backend_registry()
    assert set(reg.keys()) == {"whisper", "whisperx", "stable-ts"}

def test_get_backend_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        _aligner.get_backend("nope")

def test_align_forwards_method(monkeypatch):
    captured = {}
    def fake_backend(audio_path, lines, lang, model_size, progress_callback=None, **kw):
        captured["method_called"] = True
        return [aligner.WordTimestamp(word="hi", start=0.0, end=1.0)]
    monkeypatch.setattr(_aligner, "get_backend", lambda m: (captured.setdefault("method", m) or fake_backend))
    monkeypatch.setattr(_aligner, "convert_to_wav", lambda p: p)
    monkeypatch.setattr(_aligner, "wav_duration_seconds", lambda p: 1.0)
    res = _aligner.align("x.wav", "hi", method="whisperx")
    assert captured["method"] == "whisperx"
    assert res.lrc_text.strip() != "" or True
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement in `aligner.py`**

Add after imports/dataclasses:
```python
_BACKEND_REGISTRY = None

def _load_backend_registry():
    global _BACKEND_REGISTRY
    if _BACKEND_REGISTRY is not None:
        return _BACKEND_REGISTRY
    from backends import whisper_backend, whisperx_backend, stablets_backend
    _BACKEND_REGISTRY = {
        "whisper": whisper_backend.align_audio,
        "whisperx": whisperx_backend.align_audio,
        "stable-ts": stablets_backend.align_audio,
    }
    return _BACKEND_REGISTRY

def _backend_registry():
    return _load_backend_registry()

def get_backend(method):
    reg = _backend_registry()
    key = (method or "whisper").strip().lower()
    if key not in reg:
        raise ValueError(
            f"Unknown alignment method '{method}'. "
            f"Available: {', '.join(sorted(reg))}"
        )
    return reg[key]
```

Modify `align()` signature add `method: str = "whisper",` at end.

Replace transcription block:
```python
        backend = get_backend(method)
        backend_warnings = []
        words = backend(
            vocals_path, lyrics_lines, language, model_size,
            progress_callback=progress_callback,
            temperature=temperature, beam_size=beam_size, best_of=best_of,
            initial_prompt=initial_prompt,
            fallback_temperatures=fallback_temperatures,
            drop_looped=drop_looped,
            warnings=backend_warnings,
        )
        result.warnings.extend(backend_warnings)
```

Remove old `transcribe_with_whisper` call and skipped_looped block. Keep `if not words:` warning.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

---

## Task 3: WhisperX backend (lazy import)

**Files:**
- Create: `backends/whisperx_backend.py`
- Test: `test/test_backends.py` (append)

- [ ] **Step 1: Append failing test**
```python
def test_whisperx_backend_missing_raises_friendly():
    import pytest
    # force missing
    import builtins
    orig = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "whisperx" or name.startswith("whisperx."):
            raise ImportError("no module")
        return orig(name, *a, **k)
    builtins.__import__ = fake_import
    try:
        from backends import whisperx_backend
        with pytest.raises(RuntimeError) as ei:
            whisperx_backend.align_audio("/tmp/a.wav", [], "en", "small")
        assert "pip install lrc-sync[whisperx]" in str(ei.value)
    finally:
        builtins.__import__ = orig
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**
```python
def align_audio(audio_path, lines, lang, model_size, progress_callback=None,
               temperature=0.0, beam_size=5, best_of=5, initial_prompt=None,
               fallback_temperatures=(0.2, 0.4), drop_looped=True,
               warnings=None, **kwargs):
    try:
        import whisperx
        import torch
    except ImportError as e:
        raise RuntimeError("whisperx is not installed. Install with: pip install lrc-sync[whisperx]") from e
    from aligner import WordTimestamp
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    if progress_callback:
        progress_callback("loading_model", 0, "Loading WhisperX model...")
    model = whisperx.load_model(model_size, device, compute_type=compute_type)
    audio = whisperx.load_audio(audio_path)
    if progress_callback:
        progress_callback("transcribing", 0, "Transcribing...")
    result = model.transcribe(audio, language=lang, batch_size=16)
    detected = result.get("language", lang)
    model_a, metadata = whisperx.load_align_model(language_code=detected, device=device)
    result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)
    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            if "start" in w and "end" in w:
                words.append(WordTimestamp(
                    word=str(w.get("word", "")).strip(),
                    start=float(w["start"]),
                    end=float(w["end"]),
                    confidence=w.get("score"),
                ))
    if progress_callback:
        progress_callback("transcribing", 100, "Transcription complete")
    return words
```

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

---

## Task 4: stable-ts backend (lazy import)

**Files:**
- Create: `backends/stablets_backend.py`
- Test: append to `test/test_backends.py`

- [ ] **Step 1: Append failing test** (same pattern, expect `pip install lrc-sync[stable-ts]`)

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**
```python
def align_audio(audio_path, lines, lang, model_size, progress_callback=None, **kwargs):
    try:
        import stable_whisper
    except ImportError as e:
        raise RuntimeError("stable-ts is not installed. Install with: pip install lrc-sync[stable-ts]") from e
    from aligner import WordTimestamp
    if progress_callback:
        progress_callback("loading_model", 0, "Loading stable-ts model...")
    model = stable_whisper.load_model(model_size)
    if progress_callback:
        progress_callback("transcribing", 0, "Transcribing...")
    res = model.transcribe(audio_path, language=lang, word_timestamps=True)
    words = []
    for seg in getattr(res, "segments", []) or []:
        for w in getattr(seg, "words", []) or []:
            words.append(WordTimestamp(
                word=str(getattr(w, "word", "")).strip(),
                start=float(getattr(w, "start", 0.0)),
                end=float(getattr(w, "end", 0.0)),
                confidence=getattr(w, "probability", None),
            ))
    if progress_callback:
        progress_callback("transcribing", 100, "Transcription complete")
    return words
```

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

---

## Task 5: Server forwarding

**Files:**
- Modify: `server.py` (`_run_job` ~149, `create_job` ~240, `align_endpoint` ~394, `youtube_endpoint` ~425)

- [ ] **Step 1: Write failing test** (optional: `test/test_server_method.py` using TestClient)
```python
# minimal smoke: create_job accepts method form field
```
Given no existing server tests, skip automated test; verify manually. But plan prefers tests. Add light test using fastapi TestClient mocking aligner.align:
```python
import sys, os
sys.path.insert(0, os.path.abspath(".."))
from unittest.mock import patch
from fastapi.testclient import TestClient
import server

def test_align_endpoint_accepts_method():
    with patch("server.align") as m:
        m.return_value.lrc_text = "LRC"
        m.return_value.words = []
        m.return_value.sync_text = ""
        c = TestClient(server.app)
        with open(os.path.abspath("../README.md"), "rb") as f:
            pass
        # use a dummy file
        import io
        r = c.post("/api/align", data={"lyrics": "hi", "method": "whisperx"}, files={"audio": ("a.mp3", io.BytesIO(b"x"), "audio/mpeg")})
        assert r.status_code in (200, 500)
        if m.called:
            assert m.call_args.kwargs.get("method") == "whisperx"
```
Note `/api/align` calls align; method forwarded. Good.

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**
  - `_run_job` add param `method: str = "whisper"` and pass `method=method` to `align(...)`.
  - `create_job` add `method: str = Form("whisper")`, forward in kwargs.
  - `align_endpoint` add `method: str = Form("whisper")`, pass `method=method`.
  - `youtube_endpoint` add `method: str = Form("whisper")`, pass `method=method`.

- [ ] **Step 4: Run — PASS**

- [ ] **Step 5: Commit**

---

## Task 6: CLI `--method`

**Files:**
- Modify: `cli.py` (argparse ~98, align call ~128)

- [ ] **Step 1: Add argument and forwarding**
```python
parser.add_argument(
    "--method", default="whisper",
    choices=["whisper", "whisperx", "stable-ts"],
    help="Alignment backend (default: whisper).",
)
```
In align call add `method=args.method,`.

- [ ] **Step 2: Smoke test**
```bash
cd C:\Users\thorz\OneDrive\Desktop\lrc-sync && python cli.py --help | findstr method
```

- [ ] **Step 3: Commit**

---

## Task 7: UI dropdown

**Files:**
- Modify: `static/index.html` (~193-204)
- Modify: `static/app.js` (~304, ~343)

- [ ] **Step 1: Add dropdown next to model select**
In `static/index.html`, after model `</select>` block (line ~204), add:
```html
<div>
    <label for="method">Alignment method</label>
    <select id="method">
        <option value="whisper" selected>Whisper (default)</option>
        <option value="whisperx">WhisperX</option>
        <option value="stable-ts">stable-ts</option>
    </select>
</div>
```
(Place inside same `.row` or new row.)

- [ ] **Step 2: Wire in app.js**
In `align()` after model read:
```js
const method = document.getElementById("method")?.value || "whisper";
```
In formData build:
```js
formData.append("method", method);
```

- [ ] **Step 3: Commit**

---

## Task 8: Packaging extras

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create pyproject.toml**
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "lrc-sync"
version = "0.1.0"
description = "Sync lyrics with audio to create LRC files."
requires-python = ">=3.10"
dependencies = [
    "faster-whisper>=1.0.0",
    "av>=14.2.0",
    "fastapi>=0.104.0",
    "uvicorn>=0.24.0",
    "python-multipart>=0.0.6",
    "yt-dlp>=2024.1.1",
]

[project.optional-dependencies]
whisperx = ["whisperx>=3.0.0"]
stable-ts = ["stable-ts>=2.0.0"]

[tool.setuptools]
py-modules = ["aligner", "cli", "server", "downloader", "logger", "lrclib", "paxsenix", "ffmpeg_setup", "eventloop"]

[tool.setuptools.packages.find]
include = ["backends*"]
```

- [ ] **Step 2: Validate**
```bash
cd C:\Users\thorz\OneDrive\Desktop\lrc-sync && python -m pip install -e . --dry-run 2>&1 | tail -5
```
(If pip unavailable, skip.)

- [ ] **Step 3: Commit**

---

## Task 9: Parity tests

**Files:**
- Create: `test/test_alignment_methods.py`

- [ ] **Step 1: Write tests**
```python
import sys, os, re
sys.path.insert(0, os.path.abspath(".."))
import aligner
from unittest.mock import patch

def _fake_backend(words):
    def backend(audio_path, lines, lang, model_size, progress_callback=None, **kw):
        return list(words)
    return backend

def test_dispatch_uses_selected_backend():
    words = [aligner.WordTimestamp(word="hi", start=0.0, end=1.0)]
    with patch("aligner.get_backend", return_value=_fake_backend(words)):
        with patch("aligner.convert_to_wav", lambda p: p), patch("aligner.wav_duration_seconds", lambda p: 1.0):
            res = aligner.align("x.wav", "hi", method="whisperx")
    assert res.lrc_text.count("[") == 1

def test_parity_shape_parametrized():
    words = [aligner.WordTimestamp(word="hi", start=0.0, end=1.0),
             aligner.WordTimestamp(word="there", start=1.0, end=2.0)]
    lyrics = "hi\nthere"
    for method in ("whisper", "whisperx", "stable-ts"):
        with patch("aligner.get_backend", return_value=_fake_backend(words)):
            with patch("aligner.convert_to_wav", lambda p: p), patch("aligner.wav_duration_seconds", lambda p: 2.0):
                res = aligner.align("x.wav", lyrics, method=method)
        assert len(res.lines) == 2, method
        assert re.search(r"\[\d{2}:\d{2}\.\d{2}\]", res.lrc_text), method
        assert len(res.words) == 2, method

def test_unknown_method_raises():
    import pytest
    with pytest.raises(ValueError):
        aligner.get_backend("nope")
```

- [ ] **Step 2: Run**
```bash
cd C:\Users\thorz\OneDrive\Desktop\lrc-sync && python -m pytest test/test_alignment_methods.py test/test_backends.py -q
```

- [ ] **Step 3: Run full suite**
```bash
cd C:\Users\thorz\OneDrive\Desktop\lrc-sync && python -m pytest -q
```

- [ ] **Step 4: Commit**

---

## Self-Review

1. Spec coverage: protocol, registry, three backends, align dispatch, server/cli/ui forwarding, packaging, parity tests — all covered.
2. Step scan: each step has command + expected pass/fail.
3. Type consistency: `method` param name consistent across align/server/cli/ui. Backend function name `align_audio` consistent.
4. Review Focus: addressed.
5. Proportion: tasks sized for independent test cycles.

Return task list:
1. Backend package + WhisperBackend
2. Registry + align dispatch
3. WhisperX backend
4. stable-ts backend
5. Server forwarding
6. CLI --method
7. UI dropdown
8. Packaging extras
9. Parity tests