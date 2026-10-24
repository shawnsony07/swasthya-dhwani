"""Per-call telemetry collector for the voice agent.

Pure Python (no LiveKit import) so it is unit-testable. The entrypoint
feeds it from LiveKit's `metrics_collected` events. It only ever reports
what was actually observed: a metric with no samples is omitted from
`snapshot()`, and the dashboard shows that as "no data" (never 0).
"""
from __future__ import annotations

from datetime import UTC, datetime
from statistics import fmean
from typing import Any


class CallMetricsCollector:
    def __init__(
        self,
        *,
        room: str | None = None,
        channel: str = "unknown",
        language: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        tts_voice: str | None = None,
        llm_model: str | None = None,
        now: datetime | None = None,
    ) -> None:
        self.connected_at = now or datetime.now(UTC)
        self.room = room
        self.channel = channel
        self.language = language
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.llm_model = llm_model
        self.readback_attempts = 0
        self.fallback_used = False
        self._stt_conf: list[float] = []
        self._tts_ttfb: list[float] = []
        self._llm_ttft: list[float] = []
        self._eou: list[float] = []

    # -- feeders -----------------------------------------------------
    def record_stt_confidence(self, confidence: float | None) -> None:
        if isinstance(confidence, (int, float)) and 0.0 <= confidence <= 1.0:
            self._stt_conf.append(float(confidence))

    def record_tts_ttfb(self, seconds: float | None) -> None:
        if isinstance(seconds, (int, float)) and seconds >= 0:
            self._tts_ttfb.append(float(seconds) * 1000.0)

    def record_llm_ttft(self, seconds: float | None) -> None:
        if isinstance(seconds, (int, float)) and seconds >= 0:
            self._llm_ttft.append(float(seconds) * 1000.0)

    def record_eou_delay(self, seconds: float | None) -> None:
        if isinstance(seconds, (int, float)) and seconds >= 0:
            self._eou.append(float(seconds) * 1000.0)

    def record_readback_attempt(self) -> None:
        self.readback_attempts += 1

    def mark_fallback_used(self) -> None:
        self.fallback_used = True

    def ingest_livekit_metric(self, metric: Any) -> None:
        """Best-effort routing of a LiveKit metrics object by its `type`.
        Unknown shapes are ignored rather than raising mid-call."""
        kind = getattr(metric, "type", None)
        if kind == "tts_metrics":
            self.record_tts_ttfb(getattr(metric, "ttfb", None))
        elif kind == "llm_metrics":
            self.record_llm_ttft(getattr(metric, "ttft", None))
        elif kind == "eou_metrics":
            self.record_eou_delay(getattr(metric, "end_of_utterance_delay", None))

    # -- output ------------------------------------------------------
    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        ended = now or datetime.now(UTC)
        out: dict[str, Any] = {
            "connected_at": self.connected_at.isoformat(),
            "ended_at": ended.isoformat(),
            "call_duration_seconds": round((ended - self.connected_at).total_seconds(), 1),
            "channel": self.channel,
            "readback_attempts": self.readback_attempts,
            "fallback_used": self.fallback_used,
        }
        for key, value in (
            ("room", self.room),
            ("language", self.language),
            ("stt_model", self.stt_model),
            ("tts_model", self.tts_model),
            ("tts_voice", self.tts_voice),
            ("llm_model", self.llm_model),
        ):
            if value:
                out[key] = value
        if self._stt_conf:
            out["stt_confidence_mean"] = round(fmean(self._stt_conf), 4)
            out["stt_utterances"] = len(self._stt_conf)
        if self._tts_ttfb:
            out["tts_ttfb_ms_mean"] = round(fmean(self._tts_ttfb), 1)
            out["tts_turns"] = len(self._tts_ttfb)
        if self._llm_ttft:
            out["llm_ttft_ms_mean"] = round(fmean(self._llm_ttft), 1)
        if self._eou:
            out["eou_delay_ms_mean"] = round(fmean(self._eou), 1)
        return out
