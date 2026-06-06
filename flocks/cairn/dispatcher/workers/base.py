from __future__ import annotations

import abc
import re
import shlex
import uuid
from dataclasses import dataclass, field

from flocks.cairn.dispatcher.config import WorkerConfig
from flocks.cairn.dispatcher.runtime.process import ProcessResult


@dataclass(slots=True)
class DriverResult:
    argv: list[str]
    session: str | None = None


@dataclass(slots=True)
class DirectExecuteResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    timed_out: bool = False
    cancelled: bool = False
    cancel_reason: str | None = None
    session: str | None = None

    def to_process_result(self) -> ProcessResult:
        return ProcessResult(
            stdout=self.stdout,
            stderr=self.stderr,
            returncode=self.returncode,
            timed_out=self.timed_out,
            cancelled=self.cancelled,
            cancel_reason=self.cancel_reason,
            session=self.session,
        )


class WorkerDriver(abc.ABC):
    type_name: str

    def supports_conclude(self) -> bool:
        return True

    def can_execute_direct(self) -> bool:
        """If True, execute_direct() is used instead of container-based execution."""
        return False

    def prepare_session(self) -> str | None:
        return None

    def build_startup_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return self.build_healthcheck(worker)

    def describe_startup_healthcheck(self, worker: WorkerConfig) -> str:
        return shlex.join(self.build_startup_healthcheck(worker))

    @abc.abstractmethod
    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def build_execute(self, worker: WorkerConfig, prompt: str, session: str | None) -> DriverResult:
        raise NotImplementedError

    @abc.abstractmethod
    def build_conclude(self, worker: WorkerConfig, prompt: str, session: str) -> list[str]:
        raise NotImplementedError

    def execute_direct(
        self,
        worker: WorkerConfig,
        prompt: str,
        *,
        phase: str,
        timeout_seconds: float = 300,
        cancellation: object | None = None,
    ) -> DirectExecuteResult:
        raise NotImplementedError("direct execution not supported")

    def extract_session(self, session: str | None, stdout: str, stderr: str) -> str | None:
        return session

    def extract_response_text(self, stdout: str, stderr: str) -> str:
        return stdout


class SeedSessionDriver(WorkerDriver):
    def prepare_session(self) -> str | None:
        return str(uuid.uuid4())


class RegexSessionDriver(WorkerDriver):
    session_pattern = re.compile(r"session id:\s*([0-9a-fA-F-]+)")

    def extract_session(self, session: str | None, stdout: str, stderr: str) -> str | None:
        if session:
            return session
        match = self.session_pattern.search(stderr)
        if match:
            return match.group(1)
        return None