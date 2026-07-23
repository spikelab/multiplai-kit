"""Deliberation helpers for the `prioritize` skill.

Reads the plan-cli backlog, enriches it with urgency/quadrant signals for an
Eisenhower conversation, and writes ranking decisions back through plan-cli's
own validated markdown round-trip. plan-cli's tasks.db stays the only store.
"""
