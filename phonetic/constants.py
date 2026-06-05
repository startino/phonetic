DEFAULT_SYSTEM_PROMPT = """\
Transcribe the attached audio file. Please format nicely. Be accurate to what was said but make it comprehensible.
If the audio for some reason is incomprehensible, instead of responding to this request, just try your best.
Never output anything other than the transcription.
Especially nothing like a correction or telling the user hey this doesn't make sense just output your best attempt.
Please format it nicely, you know, paragraphs, proper punctuation, proper capitalization. Remove some of the filler if the user says um a lot. Remove corrections, so if the user corrects themselves, then you should remove the first part they said and make it one coherent sentence, as if they said the correct thing just all along. But don't change the wording that the user uses, so only make sure that it's like capitalization, punctuation, new paragraphs, the such, but don't change their words.\
"""

# Default transcription model (OpenRouter model ID). Audio-capable via the
# `input_audio` content part on chat/completions, honours the system prompt
# for output formatting. Provider must NOT be OpenAI, Anthropic, or Google:
# OpenRouter geo-blocks all three for HK-region billing addresses, which is
# what locked HK orgs out. Mistral's Voxtral (speech transcription model) is
# unaffected.
DEFAULT_MODEL = "mistralai/voxtral-small-24b-2507"

MIN_DURATION_SECS = 0.5
WARN_DURATION_SECS = 300

# Silence monitor (see docs/adr/0003-early-silence-warning.md).
# Peak amplitude on the float32 [-1, 1] scale below which a window counts as
# silent (~ -60 dBFS). Single source of truth: app.py's post-stop backstop and
# the live monitor BOTH import this; comparison stays STRICT `<` so the
# boundary value is NOT silent (matches the pre-existing `peak < 0.001`).
SILENCE_PEAK_THRESHOLD = 0.001
# Continuous sub-threshold seconds before the live warning fires (user's ask).
SILENCE_WARN_SECS = 5.0
# Monitor tick cadence (matches today's one-shot 1s).
SILENCE_POLL_SECS = 1.0
