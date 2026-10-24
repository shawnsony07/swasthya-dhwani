from livekit import rtc

from swasthya.voice.audio_tee import TurnAudioBuffer


def _frame(samples: int = 160) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=bytes(samples * 2), sample_rate=16000, num_channels=1, samples_per_channel=samples
    )


def test_empty_buffer_has_no_audio():
    buf = TurnAudioBuffer()
    assert not buf.has_audio()
    assert buf.snapshot_and_clear() == b""


def test_push_then_snapshot_returns_wav_bytes_and_clears():
    buf = TurnAudioBuffer()
    buf.push(_frame())
    buf.push(_frame())
    assert buf.has_audio()

    clip = buf.snapshot_and_clear()

    assert clip != b""
    assert clip[:4] == b"RIFF"  # WAV container header
    assert not buf.has_audio()
    assert buf.snapshot_and_clear() == b""  # second snapshot after clear is empty


def test_discard_drops_buffered_audio_without_a_clip():
    buf = TurnAudioBuffer()
    buf.push(_frame())
    buf.discard()
    assert not buf.has_audio()
    assert buf.snapshot_and_clear() == b""


def test_buffer_caps_at_max_frames_and_counts_drops():
    buf = TurnAudioBuffer(max_buffered_frames=3)
    for _ in range(5):
        buf.push(_frame())

    assert buf.dropped_frame_count == 2

    clip = buf.snapshot_and_clear()
    assert clip != b""
    # dropped counter resets with the buffer for the next turn
    assert buf.dropped_frame_count == 0


def test_successive_turns_are_independent():
    buf = TurnAudioBuffer()
    buf.push(_frame())
    first_clip = buf.snapshot_and_clear()

    buf.push(_frame())
    buf.push(_frame())
    second_clip = buf.snapshot_and_clear()

    assert first_clip != b""
    assert second_clip != b""
    assert len(second_clip) > len(first_clip)
