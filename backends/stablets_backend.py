def align_audio(audio_path, lines, lang, model_size, progress_callback=None, **kwargs):
    try:
        import stable_whisper
    except ImportError as e:
        raise RuntimeError("stable-ts is not installed. Install with: pip install stable-ts") from e
    from aligner import WordTimestamp
    if progress_callback:
        progress_callback("loading_model", 0, "Loading stable-ts model...")
    model = stable_whisper.load_model(model_size)
    if progress_callback:
        progress_callback("transcribing", 0, "Transcribing...")
    def _st_cb(seek, total=None, *rest):
        if isinstance(seek, (tuple, list)):
            if len(seek) >= 2 and seek[1]:
                total = seek[1]
                seek = seek[0]
            else:
                seek = seek[0] if seek else 0
                total = None
        if total:
            pct = int(seek / total * 100)
        else:
            pct = int(seek)
        pct = max(0, min(100, pct))
        if progress_callback:
            progress_callback("transcribing", max(0, min(99, pct)), f"Transcribing... {pct}%")
    res = model.transcribe(audio_path, language=lang, word_timestamps=True, progress_callback=_st_cb)
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