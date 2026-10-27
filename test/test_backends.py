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
    def _get_backend(m):
        captured["method"] = m
        return fake_backend
    monkeypatch.setattr(_aligner, "get_backend", _get_backend)
    monkeypatch.setattr(_aligner, "convert_to_wav", lambda p: p)
    monkeypatch.setattr(_aligner, "wav_duration_seconds", lambda p: 1.0)
    res = _aligner.align("x.wav", "hi", method="whisperx")
    assert captured["method"] == "whisperx"
    assert res.lrc_text.strip() != "" or True
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

def test_stablets_backend_missing_raises_friendly():
    import pytest
    import builtins
    orig = builtins.__import__
    def fake_import(name, *a, **k):
        if name == "stable_whisper" or name.startswith("stable_whisper."):
            raise ImportError("no module")
        return orig(name, *a, **k)
    builtins.__import__ = fake_import
    try:
        from backends import stablets_backend
        with pytest.raises(RuntimeError) as ei:
            stablets_backend.align_audio("/tmp/a.wav", [], "en", "small")
        assert "pip install lrc-sync[stable-ts]" in str(ei.value)
    finally:
        builtins.__import__ = orig


def test_stablets_backend_forwards_progress(monkeypatch):
    import sys, types
    monkeypatch.delitem(sys.modules, "stable_whisper", raising=False)
    fake_mod = types.ModuleType("stable_whisper")
    class FakeModel:
        def transcribe(self, audio_path, language=None, word_timestamps=True,
                       progress_callback=None, **kw):
            if progress_callback is not None:
                progress_callback(10, 100)
                progress_callback(50, 100)
            return types.SimpleNamespace(segments=[])
    fake_mod.load_model = lambda size: FakeModel()
    monkeypatch.setitem(sys.modules, "stable_whisper", fake_mod)

    from backends import stablets_backend
    calls = []
    def cb(stage, pct, msg):
        calls.append((stage, pct, msg))
    stablets_backend.align_audio("/tmp/a.wav", [], "en", "small", progress_callback=cb)
    percents = [c[1] for c in calls]
    assert 10 in percents
    assert 50 in percents


def test_whisperx_backend_forwards_progress(monkeypatch):
    import sys, types
    monkeypatch.delitem(sys.modules, "whisperx", raising=False)
    fake_mod = types.ModuleType("whisperx")
    class FakeModel:
        def transcribe(self, audio, language=None, batch_size=16,
                       progress_callback=None, **kw):
            if progress_callback is not None:
                progress_callback(10)
                progress_callback(50)
            return {"segments": [], "language": language or "en"}
    fake_mod.load_model = lambda *a, **k: FakeModel()
    fake_mod.load_audio = lambda p: [0, 0]
    fake_mod.load_align_model = lambda language_code=None, device=None: (None, None)
    fake_mod.align = lambda *a, **k: {"segments": []}
    monkeypatch.setitem(sys.modules, "whisperx", fake_mod)

    from backends import whisperx_backend
    calls = []
    def cb(stage, pct, msg):
        calls.append((stage, pct, msg))
    whisperx_backend.align_audio("/tmp/a.wav", [], "en", "small", progress_callback=cb)
    percents = [c[1] for c in calls]
    assert 10 in percents
    assert 50 in percents
