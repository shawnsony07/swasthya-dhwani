"""Dedicated exception types for the workflow state machine.

One class per failure mode, per the project's error-handling convention —
callers (the A2A handler, the dashboard approve endpoint, the timeout
sweeper) can catch exactly the failure they know how to handle instead of
pattern-matching on message strings.
"""
from __future__ import annotations


class WorkflowError(Exception):
    """Base class for all workflow state-machine errors."""


class TaskNotFoundError(WorkflowError):
    """Raised when a task_id does not exist in the `tasks` table."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"task {task_id!r} not found")


class IllegalTransitionError(WorkflowError):
    """Raised when a requested state transition is not in ALLOWED_TRANSITIONS.

    This is the guardrail that keeps the state machine from being able to
    silently skip states (e.g. straight from AWAITING_APPROVAL to
    COMPLETED) the way the pre-fix timeout path used to.
    """

    def __init__(self, task_id: str, current_state: str, new_state: str) -> None:
        self.task_id = task_id
        self.current_state = current_state
        self.new_state = new_state
        super().__init__(
            f"task {task_id!r}: illegal transition {current_state!r} -> {new_state!r}"
        )


class MissingHospitalForEscalationError(WorkflowError):
    """Raised when a task reaches timeout escalation with no hospital set.

    This is the T4 safety fix (architecture.md section 5): the old bug let
    a timeout silently "approve" a case with `hospital: None`, which means
    nobody was ever told where to go. Today the rule engine must have
    already chosen a hospital by the time a case is AWAITING_APPROVAL, so
    `hospital is None` here means a caller upstream forgot to set it — a
    bug to surface loudly, not a condition to paper over with a default.
    """

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(
            f"task {task_id!r}: cannot auto-escalate with no hospital chosen "
            "(this would reproduce the T4 bug: approved/escalated with no "
            "destination). The rule engine must set Task.hospital before the "
            "task enters AWAITING_APPROVAL."
        )
