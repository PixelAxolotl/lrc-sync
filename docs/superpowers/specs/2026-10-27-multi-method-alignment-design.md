# Multi-Method Alignment Design

Date: 2026-10-27
Status: Approved design (no code changes yet)

## 1. Intent

Add selectable alignment backends (whisper, whisperx, stable-ts) behind the existing
`align()` entry point, keeping whisper as the default. Expose selection via a UI
dropdown and a CLI flag. All backends return the identical `AlignmentResult.words` +
spans shape so LRC generation, word JSON, and char-level sync remain unchanged.

Approved decisions:
- UX: Dropdown + CLI flag, existing whisper stays default
- Deps: Optional extras, base install stays light
- Parity: Full parity - all methods return identical AlignmentResult.words + spans so LRC, word JSON, char sync keep working
- Approach: Pluggable backends

## 2. Architecture

Backend protocol:

```text
align_audio(audio_path, lines, lang, model_size, progress_callback=None) -> list[WordTimestamp]
```

- Returns only word timestamps in the existing `WordTimestamp` shape (word, start, end, ...).
- Per-line spans stay produced by `match_lyrics_to_words` post-processing, exactly as today
  (aligner.py:1107-1113). No backend emits spans, so all methods get identical span logic.
- The whisper backend wraps `transcribe_with_whisper`, forwarding `model_size`,
  `progress_callback`, `temperature`, `beam_size`, `best_of`, `initial_prompt`,
  `fallback_temperatures`, `drop_looped` unchanged; its skipped-looped-segment
  warnings surface through `result.warnings` as today.

Registry keyed by method name:

```text
{ "whisper": WhisperBackend, "whisperx": WhisperXBackend, "stable-ts": StableTSBackend }
```

`align()` (aligner.py:981) accepts a `method` parameter, resolves the backend from
the registry, and delegates transcription/alignment to it. Post-processing
(`match_lyrics_to_words` aligner.py:538, formatting) is method-agnostic and runs on
the returned `WordTimestamp` list.

## 3. Components / Files

- `aligner.py`: registry + `align()` dispatch + backend protocol definition.
- `backends/whisper_backend.py`: wraps existing `transcribe_with_whisper` (aligner.py:416-509).
- `backends/whisperx_backend.py`: lazy import of `whisperx`; adapter to `WordTimestamp`.
- `backends/stablets_backend.py`: lazy import of `stable_whisper`; adapter to `WordTimestamp`.
- `server.py` / `static/`: method dropdown in `static/index.html` + `static/app.js`,
  next to the existing model select; all `align()` call sites forward `method` —
  job pipeline (server.py:182-195, served by the `/sync` endpoint at server.py:354),
  `/api/align` (server.py:412), and `/api/youtube` (server.py:441). All default
  to `whisper`, so no call site behaviour forks.
- `cli.py`: `--method` flag, default `whisper`, forwarded at the `align()` call
  (cli.py:128).
- `requirements.txt` / packaging: optional extras
  (`pip install lrc-sync[whisperx]`, `[stable-ts]`); base stays light. The repo
  currently ships only `requirements.txt` with no packaging metadata, so adding
  `pyproject.toml` with these extras is part of this work.

## 4. Data Flow

UI dropdown / CLI `--method` -> request/args carry `method` -> `align()` resolves
backend from registry -> backend returns a `WordTimestamp` list (existing shape) ->
`match_lyrics_to_words` produces lines + spans exactly as today; `format_lrc`,
sync JSON, `_char_times_for_line` consume unchanged output. No changes downstream
of `match_lyrics_to_words`.

## 5. Error Handling

- Lazy imports inside each backend; missing extra raises a friendly message naming
  the install command (e.g. `pip install lrc-sync[whisperx]`).
- Per-backend try/except around transcription; surface a clear error, no silent
  swallowing.
- Fallback to whisper only when explicitly requested via a flag; never implicit.
- Log per-word confidence where the backend provides it.

## 6. Testing

- Existing pytest suite must stay green on whisper default.
- New parity tests: for a short fixture audio, each available backend's LRC output
  matches the expected shape (line count, timestamp format, word count) without
  requiring model downloads in CI (mocked backends / skipped when extra absent).
- No model downloads in CI.

## 7. Out of Scope

- No auto-fallback chain between backends.
- No benchmark/compare UI.
- No Demucs coupling.

## 8. Project Context Refs

- `align()` in `aligner.py:981`
- `transcribe_with_whisper` `aligner.py:416-509`
- `match_lyrics_to_words` `aligner.py:538-704`
- spans produced at `aligner.py:1107-1113`
- `server.py:182-195`, `server.py:412`, `server.py:441`, `cli.py:128` call `align()`
- `server.py:354` sync endpoint
- `static/index.html` model select (dropdown template)
