from __future__ import annotations

import shlex

from flocks.cairn.dispatcher.config import WorkerConfig
from flocks.cairn.dispatcher.workers.base import DriverResult, RegexSessionDriver


class ClaudeCodeDriver(RegexSessionDriver):
    type_name = "claudecode"

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return ["sh", "-c", "echo ok"]

    def build_execute(self, worker: WorkerConfig, prompt: str, session: str | None) -> DriverResult:
        argv = [
            "claude",
            "-p", prompt,
        ]
        if session:
            argv.extend(["--resume", session])
        return DriverResult(argv=argv, session=session)

    def build_conclude(self, worker: WorkerConfig, prompt: str, session: str) -> list[str]:
        return ["claude", "-p", prompt, "--resume", session]