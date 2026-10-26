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
