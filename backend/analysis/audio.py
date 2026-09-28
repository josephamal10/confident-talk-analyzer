"""Audio decoding and voice activity detection."""
from faster_whisper import decode_audio
from faster_whisper.vad import VadOptions, get_speech_timestamps

SAMPLE_RATE = 16000

# Pause analysis needs short silences, so keep Silero's gaps down to 100 ms
# (faster-whisper's 2 s default is tuned for chunking audio, not for measuring pauses).
_VAD_OPTIONS = VadOptions(min_silence_duration_ms=100, speech_pad_ms=30)


def load_audio(path):
    """Decodes any browser recording format (webm, ogg, mp4, wav) to mono 16 kHz float32."""
    return decode_audio(path, sampling_rate=SAMPLE_RATE)


def detect_speech(audio):
    """Returns speech regions as (start, end) tuples in seconds, using the Silero VAD model."""
    if len(audio) < SAMPLE_RATE // 10:
        return []
    timestamps = get_speech_timestamps(audio, _VAD_OPTIONS, sampling_rate=SAMPLE_RATE)
    return [(ts["start"] / SAMPLE_RATE, ts["end"] / SAMPLE_RATE) for ts in timestamps]
