"""Per-turn audio buffering for the speech interpreter.

docs/architecture.md section 4: "the `stt_node` override tees each user
turn's audio into a short in-memory buffer while Sarvam produces the
transcript. The interpreter gets the clip and the transcript together,
because the transcript alone is what fails on impaired speech."

This module holds only the buffering mechanics (push frames, snapshot a
turn's audio as WAV bytes, clear for the next turn) and depends on nothing
beyond `livekit.rtc`/`livekit.agents.utils`, so it can be unit-tested with
synthetic `AudioFrame`s and no live LiveKit room or STT.
"""
from __future__ import annotations

from livekit import rtc
from livekit.agents import utils

# A turn's audio clip is bounded so a caller who never stops talking (or a
# missed end-of-speech event) cannot grow this buffer without limit. At
# 16kHz mono 16-bit, this generously covers several minutes of speech —
# architecture.md's own flows expect short turns ("one question per turn").
_MAX_BUFFERED_FRAMES = 4096


class TurnAudioBuffer:
    """Accumulates raw audio frames for the turn currently in progress."""

    def __init__(self, max_buffered_frames: int = _MAX_BUFFERED_FRAMES) -> None:
        self._frames: list[rtc.AudioFrame] = []
        self._max_buffered_frames = max_buffered_frames
        self._dropped_frames = 0

    def push(self, frame: rtc.AudioFrame) -> None:
        if len(self._frames) >= self._max_buffered_frames:
            self._dropped_frames += 1
            return
        self._frames.append(frame)

    @property
    def dropped_frame_count(self) -> int:
        """Frames silently dropped because the buffer was full. A nonzero
        count means the interpreter's clip is missing tail audio for an
        unusually long turn — surfaced so callers can log/alert on it."""
        return self._dropped_frames

    def has_audio(self) -> bool:
        return bool(self._frames)

    def snapshot_and_clear(self) -> bytes:
        """Returns the buffered turn's audio as WAV bytes and resets the
        buffer for the next turn. Returns `b""` if nothing was buffered —
        callers must treat that as "no clip available", not a silent clip."""
        if not self._frames:
            return b""
        combined = utils.combine_frames(self._frames)
        wav_bytes = combined.to_wav_bytes()
        self._frames = []
        self._dropped_frames = 0
        return wav_bytes

    def discard(self) -> None:
        """Drops the current turn's audio without producing a clip (e.g. a
        turn that ended in silence/no final transcript)."""
        self._frames = []
        self._dropped_frames = 0
