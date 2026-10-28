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
            res = aligner.align("x.wav", "hi", method="stable-ts")
    assert res.lrc_text.count("[") == 1

def test_parity_shape_parametrized():
    words = [aligner.WordTimestamp(word="hi", start=0.0, end=1.0),
             aligner.WordTimestamp(word="there", start=1.0, end=2.0)]
    lyrics = "hi\nthere"
    for method in ("stable-ts", "whisper"):
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