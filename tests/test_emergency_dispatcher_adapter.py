"""Integration test for `entrypoint._EmergencyDispatcherAdapter`: the real
`ActionGateway` (allow-list, rate limiter, kill switch, audit) driven end to
end, not a fake. Complements `test_gateway.py` (gateway policy alone) and
`test_conversation.py` (orchestrator against a fake `EmergencyDispatcher`).
"""
from __future__ import annotations

import swasthya.voice.entrypoint as entrypoint_module
from swasthya.contracts import ActionOutcome
from swasthya.voice.entrypoint import _EmergencyDispatcherAdapter, _get_action_gateway


def _reset_gateway_singleton() -> None:
    """The gateway/allow-list are process-wide singletons by design (kill
    switch and rate limits must persist across calls) — tests need a clean
    slate, so reset the module-level state directly."""
    entrypoint_module._action_gateway = None
    entrypoint_module._gateway_allow_list = None


async def test_unenrolled_caller_falls_back_to_default_on_call_contact(monkeypatch):
    _reset_gateway_singleton()
    monkeypatch.setenv("DEFAULT_EMERGENCY_CONTACT", "oncall-default")
    adapter = _EmergencyDispatcherAdapter()

    outcome = await adapter.dispatch_emergency("", "emergency message")

    assert outcome is ActionOutcome.EMERGENCY_CALLED
    _, allow_list = _get_action_gateway()
    assert allow_list.ordered_targets("unknown_caller") == ["oncall-default"]


async def test_enrolled_caller_tries_own_contacts_first(monkeypatch):
    _reset_gateway_singleton()
    monkeypatch.setenv("DEFAULT_EMERGENCY_CONTACT", "oncall-default")
    adapter = _EmergencyDispatcherAdapter()
    _, allow_list = _get_action_gateway()
    allow_list.add_entry("patient-1", "caregiver-1", kind="contact")

    outcome = await adapter.dispatch_emergency("patient-1", "emergency message")

    assert outcome is ActionOutcome.EMERGENCY_CALLED
    # The patient's own enrolled contact was used, never the system default.
    assert "oncall-default" not in allow_list.ordered_targets("patient-1")


async def test_no_enrolled_contact_and_no_default_configured_fails_without_crashing(
    monkeypatch,
):
    _reset_gateway_singleton()
    monkeypatch.delenv("DEFAULT_EMERGENCY_CONTACT", raising=False)
    adapter = _EmergencyDispatcherAdapter()

    outcome = await adapter.dispatch_emergency("nobody-enrolled", "emergency message")

    assert outcome is ActionOutcome.EMERGENCY_CALL_FAILED


async def test_first_contact_failing_falls_through_to_the_next_one(monkeypatch):
    _reset_gateway_singleton()
    monkeypatch.delenv("DEFAULT_EMERGENCY_CONTACT", raising=False)
    adapter = _EmergencyDispatcherAdapter()
    _, allow_list = _get_action_gateway()
    # "-offline-" is one of null_providers' forced-failure markers.
    allow_list.add_entry("patient-2", "contact-offline-1", kind="contact")
    allow_list.add_entry("patient-2", "contact-2", kind="contact")

    outcome = await adapter.dispatch_emergency("patient-2", "emergency message")

    assert outcome is ActionOutcome.EMERGENCY_CALLED


async def test_kill_switch_blocks_dispatch_but_the_attempt_is_still_audited(monkeypatch):
    _reset_gateway_singleton()
    monkeypatch.setenv("DEFAULT_EMERGENCY_CONTACT", "oncall-default")
    adapter = _EmergencyDispatcherAdapter()
    gateway, _ = _get_action_gateway()
    gateway._kill_switch.engage(by="test", reason="drill")

    outcome = await adapter.dispatch_emergency("patient-3", "emergency message")

    assert outcome is ActionOutcome.REJECTED
    assert any(a.action_type.value == "emergency_call" for a in gateway.alerts)
