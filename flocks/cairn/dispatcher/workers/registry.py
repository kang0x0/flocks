from __future__ import annotations

from flocks.cairn.dispatcher.workers.adapters.claudecode import ClaudeCodeDriver
from flocks.cairn.dispatcher.workers.adapters.codex import CodexDriver
from flocks.cairn.dispatcher.workers.adapters.flocks import FlocksDriver
from flocks.cairn.dispatcher.workers.adapters.mock import MockDriver
from flocks.cairn.dispatcher.workers.adapters.pi import PiDriver
from flocks.cairn.dispatcher.workers.base import WorkerDriver


DRIVERS: dict[str, WorkerDriver] = {
    "mock": MockDriver(),
    "flocks": FlocksDriver(),
    "claudecode": ClaudeCodeDriver(),
    "codex": CodexDriver(),
    "pi": PiDriver(),
}


def get_driver(name: str) -> WorkerDriver:
    return DRIVERS[name]