from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docker.models.containers import Container

LOG = logging.getLogger(__name__)

EXEC_KILL_JOIN_TIMEOUT_SECONDS = 5.0


@dataclass(slots=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False
    cancel_reason: str | None = None
    session: str | None = None


class ManagedProcess:
    def __init__(self, container: Container, command: list[str], env: dict[str, str]):
        self.command = command
        self.env = env
        self._container = container
        self._api = container.client.api
        self._exec_id: str | None = None
        self._reader: threading.Thread | None = None
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._returncode: int | None = None
        self._timed_out = False
        self._cancel_reason: str | None = None
        self._read_error: str | None = None
        self._done = threading.Event()