from __future__ import annotations

from flocks.cairn.dispatcher.config import WorkerConfig
from flocks.cairn.dispatcher.workers.base import DriverResult, SeedSessionDriver


class CodexDriver(SeedSessionDriver):
    type_name = "codex"

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return ["sh", "-c", "echo ok"]

    def build_execute(self, worker: WorkerConfig, prompt: str, session: str | None) -> DriverResult:
        argv = [
            "codex",
            "exec",
            "--session", session or "",
            "-m", "claude-opus-4-20250514",
            "-p", prompt,
        ]
        return DriverResult(argv=argv, session=session)

    def build_conclude(self, worker: WorkerConfig, prompt: str, session: str) -> list[str]:
        return [
            "codex",
            "exec",
            "--session", session,
            "-m", "claude-opus-4-20250514",
            "-p", prompt,
        ]