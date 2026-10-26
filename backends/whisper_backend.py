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
