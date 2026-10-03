"""Tests for progress callbacks and the job system (all external work mocked)."""

import pytest
from unittest.mock import patch

import aligner
from aligner import WordTimestamp, AlignmentResult
import server


class TestAlignProgress:
    def test_emits_stages(self):
        events = []
        words = [WordTimestamp(word="Hello", start=1.0, end=1.5)]

        with patch.object(aligner, "convert_to_wav", return_value="out.wav"), \
             patch.object(
                 aligner, "transcribe_with_whisper",
                 side_effect=lambda wav, model, lang, progress_callback=None: (
                     progress_callback("loading_model", 0, "Loading..."),
                     progress_callback("transcribing", 50, "Half..."),
                     words,
                 )[2],
             ), \
             patch("os.path.exists", return_value=False):
            result = aligner.align(
                audio_path="in.mp3",
                lyrics_text="Hello",
                progress_callback=lambda s, p, m: events.append((s, p)),
            )

        stages = [s for s, _ in events]
        assert "converting" in stages
        assert "loading_model" in stages
        assert "transcribing" in stages
        assert "matching" in stages
        assert "done" in stages
        assert result.lines[0].start == 1.0

    def test_no_callback_still_works(self):
        words = [WordTimestamp(word="Hello", start=1.0, end=1.5)]
        with patch.object(aligner, "convert_to_wav", return_value="out.wav"), \
             patch.object(aligner, "transcribe_with_whisper", return_value=words), \
             patch("os.path.exists", return_value=False):
            result = aligner.align(audio_path="in.mp3", lyrics_text="Hello")
        assert result.lines[0].start == 1.0


class TestTranscribeVAD:
    def test_vad_filter_disabled_for_sung_music(self):
        """Regression test: VAD deleted ~90% of sung songs. Must stay off."""
        import faster_whisper

        captured = {}

        class FakeModel:
            def __init__(self, *a, **k):
                pass

            def transcribe(self, wav_path, **kwargs):
                captured.update(kwargs)
                info = type("Info", (), {"duration": 10.0})()
                return iter([]), info

        with patch.object(faster_whisper, "WhisperModel", FakeModel):
            aligner.transcribe_with_whisper("x.wav")
        assert captured.get("vad_filter") is False
        assert captured.get("word_timestamps") is True


class TestJobs:
    def _make_result(self):
        r = AlignmentResult()
        r.lrc_text = "[00:01.00]Hello\n"
        return r

    def test_run_job_success(self):
        server.jobs["job1"] = {"stage": "queued", "percent": 0, "message": "",
                               "done": False, "lrc": None, "error": None,
                               "warnings": []}
        events = []
        with patch.object(server, "download_audio", return_value="/tmp/x.mp3") as dl, \
             patch.object(server, "align", return_value=self._make_result()):
            server._run_job(
                "job1", url="http://example.com/v",
                lyrics="Hello",
                cleanup_paths=[],
            )
            dl.assert_called_once()
        job = server.jobs.pop("job1")
        assert job["done"] is True
        assert job["lrc"] == "[00:01.00]Hello\n"
        assert job["stage"] == "done"
        assert job["error"] is None

    def test_run_job_error(self):
        server.jobs["job2"] = {"stage": "queued", "percent": 0, "message": "",
                               "done": False, "lrc": None, "error": None,
                               "warnings": []}
        with patch.object(server, "align", side_effect=RuntimeError("boom")):
            server._run_job("job2", audio_path="/tmp/x.mp3", lyrics="Hi",
                            cleanup_paths=[])
        job = server.jobs.pop("job2")
        assert job["done"] is True
        assert "boom" in job["error"]
        assert job["stage"] == "error"

    def test_update_job_unknown_id_ignored(self):
        server._update_job("nope", "transcribing", 10, "hi...")
