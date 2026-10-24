"""Tests for the action gateway (src/swasthya/gateway/).

Kill-switch vs. emergency-call resolution (see action_gateway.py module
docstring for the full reasoning): the kill switch blocks *dispatch* of
every action type, including emergency calls — it does not special-case a
real call to still go out. What it never blocks is the dashboard alert: an
emergency call that is rejected because of the kill switch still raises an
alert, so a blocked emergency is loud, not silent. `test_kill_switch_*`
below encodes and asserts exactly that choice.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from swasthya.contracts import ActionOutcome, ActionRequest, ActionType, ConfirmedByAction
from swasthya.gateway.action_gateway import ActionGateway
from swasthya.gateway.allowlist import AllowList
from swasthya.gateway.kill_switch import KillSwitch
from swasthya.gateway.providers.null_providers import (
    LoggingDeviceProvider,
    LoggingEmergencyCallProvider,
    NeutralVoiceProvider,
)
from swasthya.gateway.rate_limiter import RateLimiter

PATIENT_ID = "patient-1"
NOW = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)


class CountingEmergencyProvider:
    """Wraps the logging provider to count real dispatch calls."""

    def __init__(self) -> None:
        self.calls = 0
        self._inner = LoggingEmergencyCallProvider()

    async def call(self, target: str, message: str) -> ActionOutcome:
        self.calls += 1
        return await self._inner.call(target, message)


def make_action(
    *,
    action_type: ActionType = ActionType.EMERGENCY_CALL,
    target: str = "contact-1",
    confirmed_by: ConfirmedByAction = ConfirmedByAction.PATIENT,
    confirmed_at: datetime = NOW,
    expires_at: datetime | None = None,
    payload: dict | None = None,
    action_id: str = "action-1",
    idempotency_key: str = "idem-1",
) -> ActionRequest:
    if expires_at is None:
        expires_at = confirmed_at + timedelta(seconds=30)
    return ActionRequest(
        action_id=action_id,
        idempotency_key=idempotency_key,
        type=action_type,
        target=target,
        payload=payload or {},
        confirmed_by=confirmed_by,
        confirmed_at=confirmed_at,
        expires_at=expires_at,
    )


def make_gateway(
    *,
    allow_list: AllowList | None = None,
    rate_limiter: RateLimiter | None = None,
    kill_switch: KillSwitch | None = None,
    emergency_provider=None,
    device_provider=None,
    voice_provider=None,
) -> ActionGateway:
    return ActionGateway(
        allow_list=allow_list or AllowList(),
        rate_limiter=rate_limiter or RateLimiter(max_actions=100, window_seconds=60),
        kill_switch=kill_switch or KillSwitch(),
        emergency_provider=emergency_provider or LoggingEmergencyCallProvider(),
        device_provider=device_provider or LoggingDeviceProvider(),
        voice_provider=voice_provider or NeutralVoiceProvider(),
        now_fn=lambda: NOW,
    )


def allow_listed(target: str = "contact-1") -> AllowList:
    allow_list = AllowList()
    allow_list.add_entry(PATIENT_ID, target, kind="contact")
    return allow_list


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfirmed_or_expired_action_is_rejected_without_dispatch():
    provider = CountingEmergencyProvider()
    gateway = make_gateway(allow_list=allow_listed(), emergency_provider=provider)

    expired_action = make_action(expires_at=NOW - timedelta(seconds=1))
    outcome = await gateway.dispatch(expired_action, PATIENT_ID)

    assert outcome == ActionOutcome.REJECTED
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_target_not_on_allow_list_is_rejected_without_dispatch():
    provider = CountingEmergencyProvider()
    gateway = make_gateway(allow_list=AllowList(), emergency_provider=provider)

    action = make_action(target="contact-not-enrolled")
    outcome = await gateway.dispatch(action, PATIENT_ID)

    assert outcome == ActionOutcome.REJECTED
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_kill_switch_on_blocks_device_command():
    provider = LoggingDeviceProvider()
    kill_switch = KillSwitch()
    kill_switch.engage(by="admin")
    gateway = make_gateway(
        allow_list=allow_listed("device-1"), kill_switch=kill_switch, device_provider=provider
    )

    action = make_action(action_type=ActionType.DEVICE_COMMAND, target="device-1")
    outcome = await gateway.dispatch(action, PATIENT_ID)

    assert outcome == ActionOutcome.REJECTED


@pytest.mark.asyncio
async def test_kill_switch_on_still_alerts_dashboard_for_emergency_call():
    """Documents our resolution: the kill switch blocks the emergency call's
    dispatch too, but the dashboard alert still fires — it is never
    silenced by the kill switch."""
    emergency_provider = CountingEmergencyProvider()
    kill_switch = KillSwitch()
    kill_switch.engage(by="admin")
    gateway = make_gateway(
        allow_list=allow_listed(),
        kill_switch=kill_switch,
        emergency_provider=emergency_provider,
    )

    action = make_action(action_type=ActionType.EMERGENCY_CALL)
    outcome = await gateway.dispatch(action, PATIENT_ID)

    assert outcome == ActionOutcome.REJECTED
    assert emergency_provider.calls == 0  # dispatch itself is blocked

    assert len(gateway.alerts) == 1
    alert = gateway.alerts[0]
    assert alert.action_type == ActionType.EMERGENCY_CALL
    assert alert.outcome == ActionOutcome.REJECTED


@pytest.mark.asyncio
async def test_idempotent_dispatch_calls_provider_once():
    provider = CountingEmergencyProvider()
    gateway = make_gateway(allow_list=allow_listed(), emergency_provider=provider)

    action = make_action(idempotency_key="shared-key")
    first = await gateway.dispatch(action, PATIENT_ID)
    second = await gateway.dispatch(action, PATIENT_ID)

    assert first == second
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_voice_clone_with_no_clone_id_is_always_neutral():
    gateway = make_gateway(allow_list=allow_listed("speaker-target"))

    action = make_action(
        action_type=ActionType.SPEAK_AS_PATIENT,
        target="speaker-target",
        payload={"text": "I have chest pain", "consent_recorded": True},
    )
    outcome = await gateway.dispatch(action, PATIENT_ID)

    assert outcome == ActionOutcome.SPOKEN_NEUTRAL
    assert outcome != ActionOutcome.SPOKEN_AS_PATIENT


@pytest.mark.asyncio
async def test_action_requested_audit_event_written_even_when_rejected():
    gateway = make_gateway(allow_list=AllowList())  # empty allow-list -> rejects

    action = make_action(target="not-enrolled")
    outcome = await gateway.dispatch(action, PATIENT_ID)

    assert outcome == ActionOutcome.REJECTED
    events = [e.event for e in gateway.audit_events]
    assert "action_requested" in events


@pytest.mark.asyncio
async def test_rate_limit_exceeded_rejects_without_reaching_provider():
    provider = CountingEmergencyProvider()
    rate_limiter = RateLimiter(max_actions=1, window_seconds=60)
    gateway = make_gateway(
        allow_list=allow_listed(), rate_limiter=rate_limiter, emergency_provider=provider
    )

    first = make_action(action_id="a1", idempotency_key="k1")
    second = make_action(action_id="a2", idempotency_key="k2")

    outcome1 = await gateway.dispatch(first, PATIENT_ID)
    outcome2 = await gateway.dispatch(second, PATIENT_ID)

    assert outcome1 == ActionOutcome.EMERGENCY_CALLED
    assert outcome2 == ActionOutcome.REJECTED
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_ordered_targets_returns_enrollment_order_and_dedupes():
    allow_list = AllowList()
    allow_list.add_entry(PATIENT_ID, "caregiver-1", kind="contact")
    allow_list.add_entry(PATIENT_ID, "on-call-1", kind="contact")
    allow_list.add_entry(PATIENT_ID, "caregiver-1", kind="contact")  # duplicate, ignored

    assert allow_list.ordered_targets(PATIENT_ID) == ["caregiver-1", "on-call-1"]
    assert allow_list.ordered_targets("unenrolled-patient") == []
