"""Shared debug-log toggle for Cairn dispatcher.

Allows toggling verbose debug logging (prompt / LLM response output)
at runtime via API, without restarting the server or setting env vars.
"""

from __future__ import annotations

_debug_log_enabled: bool = False


def is_debug_log_enabled() -> bool:
    """Whether verbose debug logging is currently enabled."""
    return _debug_log_enabled


def set_debug_log_enabled(enabled: bool) -> None:
    """Enable or disable verbose debug logging."""
    global _debug_log_enabled  # noqa: PLW0603
    _debug_log_enabled = enabled