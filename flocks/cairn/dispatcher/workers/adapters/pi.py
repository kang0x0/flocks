from __future__ import annotations

from flocks.cairn.dispatcher.config import WorkerConfig
from flocks.cairn.dispatcher.workers.base import DriverResult, SeedSessionDriver


class PiDriver(SeedSessionDriver):
    type_name = "pi"

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return ["sh", "-c", "echo ok"]

    def build_execute(self, worker: WorkerConfig, prompt: str, session: str | None) -> DriverResult:
        argv = [
            "pi",
            "exec",
            "-m", "gpt-4o",
            "-p", prompt,
        ]
        if session:
            argv.extend(["--session", session])
        return DriverResult(argv=argv, session=session)

    def build_conclude(self, worker: WorkerConfig, prompt: str, session: str) -> list[str]:
        return [
            "pi",
            "exec",
            "-m", "gpt-4o",
            "-p", prompt,
            "--session", session,
        ]