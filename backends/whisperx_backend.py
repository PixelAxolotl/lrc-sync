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