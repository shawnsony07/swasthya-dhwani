"""Provider abstractions for the action gateway.

Real vendor integrations (Twilio, SmartThings, a voice-cloning vendor) are
out of scope for this pass. This package defines the Protocol contracts the
gateway dispatches against, plus safe null/default implementations that do
nothing destructive. A real vendor adapter can be dropped in later by
implementing the same Protocol, with zero changes to `action_gateway.py`.
"""
