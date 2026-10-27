def align_audio(audio_path, lines, lang, model_size, progress_callback=None,
                temperature=0.0, beam_size=5, best_of=5, initial_prompt=None,
                fallback_temperatures=(0.2, 0.4), drop_looped=True,
                warnings=None, **kwargs):
    import os
    # Process-local: keep HF hub / tqdm from writing progress bars to the
    # console, where they interleave with our [INFO] lines. Progress is
    # reported through progress_callback (job dict) instead.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")
    if os.environ.get("HF_HUB_DISABLE_PROGRESS_BARS") != "1":
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    if os.environ.get("TQDM_DISABLE") != "1":
        os.environ["TQDM_DISABLE"] = "1"
    try:
        import whisperx
        import torch
    except ImportError as e:
        raise RuntimeError("whisperx/pyannote is not installed. Install with: pip install pyannote-audio  (or: pip install -e .[whisperx] / pip install lrc-sync[whisperx])") from e
    from aligner import WordTimestamp, _LOCAL_MODELS_DIR
    # Best-effort: also flip the already-imported HF constants / transformers
    # logging so bars and chatty warnings stay off without silencing errors.
    try:
        import huggingface_hub.constants as _hf_const
        _hf_const.HF_HUB_DISABLE_PROGRESS_BARS = True
    except Exception:
        pass
    try:
        import sys as _sys
        _hf_tqdm_mod = _sys.modules.get("huggingface_hub.utils.tqdm")
        if _hf_tqdm_mod is None:
            import huggingface_hub.utils.tqdm  # noqa: F401
            _hf_tqdm_mod = _sys.modules.get("huggingface_hub.utils.tqdm")
        if _hf_tqdm_mod is not None:
            _hf_tqdm_mod.HF_HUB_DISABLE_PROGRESS_BARS = True
    except Exception:
        pass
    try:
        import huggingface_hub.utils as _hf_utils
        _hf_utils.disable_progress_bars()
    except Exception:
        pass
    try:
        import transformers.utils.logging as _tf_log
        _tf_log.set_verbosity_error()
    except Exception:
        pass
    try:
        import os, inspect
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
        if progress_callback:
            progress_callback("downloading", 0, "Downloading transcription model...")
        _lm_kw = {}
        try:
            _params = inspect.signature(whisperx.load_model).parameters
            if "download_root" in _params or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _params.values()):
                _lm_kw["download_root"] = str(_LOCAL_MODELS_DIR)
        except (TypeError, ValueError):
            _lm_kw["download_root"] = str(_LOCAL_MODELS_DIR)
        try:
            model = whisperx.load_model(model_size, device, compute_type=compute_type, **_lm_kw)
        except ImportError as e:
            raise RuntimeError("whisperx/pyannote is not installed. Install with: pip install pyannote-audio  (or: pip install -e .[whisperx] / pip install lrc-sync[whisperx])") from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to load WhisperX model '{model_size}': {e}. "
                f"Check local cache at {_LOCAL_MODELS_DIR} and HF_ENDPOINT={os.environ.get('HF_ENDPOINT')}; "
                f"delete partial snapshot in %USERPROFILE%/.cache/huggingface/hub/models--Systran--faster-whisper-{model_size} if corrupted."
            ) from e
        if progress_callback:
            progress_callback("transcribing", 0, "Transcribing...")
        audio = whisperx.load_audio(audio_path)
        def _wx_cb(pct, *rest):
            if isinstance(pct, (tuple, list)):
                if len(pct) >= 2 and pct[1]:
                    pct = pct[0] / pct[1] * 100
                else:
                    pct = pct[0] if pct else 0
            elif rest and rest[0]:
                try:
                    pct = pct / rest[0] * 100
                except Exception:
                    pass
            p = int(pct) if pct is not None else 0
            p = max(0, min(100, p))
            if progress_callback:
                progress_callback("transcribing", max(0, min(99, p)), f"Transcribing... {p}%")
        result = model.transcribe(audio, language=lang, batch_size=16, progress_callback=_wx_cb)
        detected = result.get("language", lang)
        _am_kw = {}
        try:
            _aparams = inspect.signature(whisperx.load_align_model).parameters
            if "model_dir" in _aparams or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _aparams.values()):
                _am_kw["model_dir"] = str(_LOCAL_MODELS_DIR)
        except (TypeError, ValueError):
            _am_kw["model_dir"] = str(_LOCAL_MODELS_DIR)
        # If weights already cached, avoid any Hugging Face hit (and lock waits).
        _align_cached = False
        try:
            _snap_root = _LOCAL_MODELS_DIR / "models--jonatasgrosman--wav2vec2-large-xlsr-53-japanese" / "snapshots"
            if _snap_root.exists():
                _align_cached = any((_snap_root).rglob("pytorch_model.bin"))
        except Exception:
            _align_cached = False
        if _align_cached:
            try:
                _aparams = inspect.signature(whisperx.load_align_model).parameters
                if "model_cache_only" in _aparams or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _aparams.values()):
                    _am_kw["model_cache_only"] = True
            except (TypeError, ValueError):
                _am_kw["model_cache_only"] = True
        else:
            os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
        if progress_callback:
            progress_callback("downloading", 0, "Downloading align model (1.27GB, first run only)...")
        # Bound the (possibly lock-blocked) load so a stuck download cannot
        # hang the job forever. On timeout, name the lock file to delete.
        import threading as _threading
        def _align_timeout_value():
            candidates = []
            for _name in ("_ALIGN_MODEL_LOAD_TIMEOUT", "ALIGN_MODEL_LOAD_TIMEOUT",
                          "_ALIGN_LOAD_TIMEOUT", "ALIGN_LOAD_TIMEOUT",
                          "_ALIGN_TIMEOUT", "ALIGN_TIMEOUT"):
                _v = globals().get(_name, None)
                if _v is not None:
                    try:
                        candidates.append(float(_v))
                    except (TypeError, ValueError):
                        pass
            for _key in ("WHISPERX_ALIGN_TIMEOUT", "WHISPERX_ALIGN_MODEL_TIMEOUT",
                         "WHISPERX_TIMEOUT", "ALIGN_TIMEOUT"):
                _raw = os.environ.get(_key)
                if _raw is not None:
                    try:
                        candidates.append(float(_raw))
                    except (TypeError, ValueError):
                        pass
            if not candidates:
                candidates.append(1800.0)
            return max(1.0, min(candidates))
        _timeout = _align_timeout_value()
        _lock_path = None
        try:
            _lock_dir = _LOCAL_MODELS_DIR / ".locks" / "models--jonatasgrosman--wav2vec2-large-xlsr-53-japanese"
            _locks = sorted(_lock_dir.glob("*.lock")) if _lock_dir.exists() else []
            _lock_path = str(_locks[0]) if _locks else str(_lock_dir / "*.lock")
        except Exception:
            _lock_path = str(_LOCAL_MODELS_DIR / ".locks" / "models--jonatasgrosman--wav2vec2-large-xlsr-53-japanese" / "*.lock")
        _result = {"value": None, "exc": None}
        def _worker():
            try:
                _result["value"] = whisperx.load_align_model(language_code=detected, device=device, **_am_kw)
            except BaseException as _e:  # noqa: BLE001
                _result["exc"] = _e
        _t = _threading.Thread(target=_worker, daemon=True)
        _t.start()
        _t.join(_timeout)
        _timed_out = _t.is_alive() or isinstance(_result["exc"], TimeoutError)
        if _timed_out:
            raise RuntimeError(
                f"Timed out after {_timeout}s waiting to acquire lock for WhisperX alignment model "
                f"'{detected}': {_result['exc'] if _result['exc'] is not None else 'lock wait exceeded timeout'}. "
                f"Lock file: {_lock_path}. Delete the .lock (and any .incomplete blob) if no download is active, "
                f"or set HF_HUB_VERBOSITY=info to see 'Still waiting to acquire lock'."
            )
        if _result["exc"] is not None:
            _e = _result["exc"]
            if isinstance(_e, ImportError):
                raise RuntimeError("whisperx/pyannote is not installed. Install with: pip install pyannote-audio  (or: pip install -e .[whisperx] / pip install lrc-sync[whisperx])") from _e
            raise RuntimeError(
                f"Failed to load WhisperX alignment model for language '{detected}': {_e}. "
                f"Check local cache at {_LOCAL_MODELS_DIR} and HF_ENDPOINT={os.environ.get('HF_ENDPOINT')}."
            ) from _e
        model_a, metadata = _result["value"]
        if progress_callback:
            progress_callback("transcribing", 0, "Transcribing...")
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
    except ImportError as e:
        raise RuntimeError("whisperx/pyannote is not installed. Install with: pip install pyannote-audio  (or: pip install -e .[whisperx] / pip install lrc-sync[whisperx])") from e
_ALIGN_MODEL_LOAD_TIMEOUT = 1800
ALIGN_MODEL_LOAD_TIMEOUT = 1800
_ALIGN_LOAD_TIMEOUT = 1800
ALIGN_LOAD_TIMEOUT = 1800
_ALIGN_TIMEOUT = 1800
ALIGN_TIMEOUT = 1800

