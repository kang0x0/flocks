"""
Flocks Worker Driver

Calls the LLM via Flocks' SessionLoop (provides tools to the LLM).
Equivalent to how CodexDriver calls ``codex exec`` via CLI — the prompt is
rendered by Cairn's prompt templates (bootstrap.md / reason.md / explore.md)
and sent as a user message, with tools available for the LLM to use.

This driver uses the **direct execution** path (``can_execute_direct() = True``).
"""

from __future__ import annotations

import asyncio
import json
import logging as _logging
import sys as _sys

from flocks.cairn.dispatcher.config import WorkerConfig
from flocks.cairn.dispatcher.debug_log import is_debug_log_enabled
from flocks.cairn.dispatcher.workers.base import (
    DirectExecuteResult,
    DriverResult,
    SeedSessionDriver,
)

# ── Logger for this module ───────────────────────────────────────────
# We attach a handler ONLY to this module's logger and disable propagation
# to the root logger.  This ensures our INFO+ messages appear in stderr
# (captured as backend.log) while avoiding noise from third-party loggers
# (httpx, aiosqlite, etc.) that propagate to the root logger.
LOG = _logging.getLogger(__name__)
LOG.setLevel(_logging.DEBUG)  # capture DEBUG, but handler below filters at INFO
if not LOG.handlers:
    _log_handler = _logging.StreamHandler(_sys.stderr)
    _log_handler.setLevel(_logging.INFO)
    _log_handler.setFormatter(
        _logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    LOG.addHandler(_log_handler)
    LOG.propagate = False


class FlocksDriver(SeedSessionDriver):
    type_name = "flocks"

    def can_execute_direct(self) -> bool:
        return True

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return ["echo", "ok"]

    def build_execute(self, worker: WorkerConfig, prompt: str, session: str | None = None) -> DriverResult:
        argv = [
            "flocks",
            "exec",
            "--session", session or "",
            "-p", prompt,
        ]
        model = worker.env.get("FLOCKS_MODEL")
        provider = worker.env.get("FLOCKS_PROVIDER")
        if model and provider:
            argv.extend(["-m", f"{provider}/{model}"])
        elif model:
            argv.extend(["-m", model])
        return DriverResult(argv=argv, session=session)

    def build_conclude(self, worker: WorkerConfig, prompt: str, session: str) -> list[str]:
        argv = [
            "flocks",
            "exec",
            "--session", session,
            "-p", prompt,
        ]
        model = worker.env.get("FLOCKS_MODEL")
        provider = worker.env.get("FLOCKS_PROVIDER")
        if model and provider:
            argv.extend(["-m", f"{provider}/{model}"])
        elif model:
            argv.extend(["-m", model])
        return argv

    def execute_direct(
        self,
        worker: WorkerConfig,
        prompt: str,
        *,
        phase: str,
        timeout_seconds: float = 300,
        cancellation: object | None = None,
    ) -> DirectExecuteResult:
        # Healthcheck is instant — no LLM call needed
        if phase == "healthcheck":
            return DirectExecuteResult(stdout="ok", returncode=0)

        # Check pre-cancellation
        if cancellation is not None and getattr(cancellation, "is_cancelled", False):
            reason = getattr(cancellation, "reason", "cancelled") or "cancelled"
            return DirectExecuteResult(
                stderr=f"cancelled before execution: {reason}",
                returncode=1,
                cancelled=True,
                cancel_reason=reason,
            )

        try:
            return asyncio.run(
                self._execute_session(worker, prompt, phase, timeout_seconds, cancellation)
            )
        except asyncio.TimeoutError:
            LOG.warning("flocks.execute_direct.timeout phase=%s timeout=%ss", phase, timeout_seconds)
            return DirectExecuteResult(
                stderr=f"FlocksDriver execution timed out after {timeout_seconds}s",
                returncode=124,
                timed_out=True,
            )
        except Exception as exc:
            LOG.exception("flocks.execute_direct.error phase=%s", phase)
            return DirectExecuteResult(
                stderr=f"FlocksDriver.execute_direct failed: {exc}",
                returncode=1,
            )

    # ── Helper: log multi-line text as separate debug lines ───────────
    @staticmethod
    def _log_text(label: str, text: str) -> None:
        """Write a labelled multi-line block to stderr.

        Only outputs when the debug-log toggle is enabled (via the Cairn UI
        button or the ``PUT /api/cairn/debug-log`` endpoint).  Uses raw
        ``print()`` to stderr to avoid the logging system entirely —
        no timestamp / level / logger-name prefix, just the plain text.
        """
        if not is_debug_log_enabled():
            return
        print(f"=== {label} ===", file=_sys.stderr, flush=True)
        print(text, file=_sys.stderr, flush=True)
        print(f"=== END {label} ===", file=_sys.stderr, flush=True)

    async def _execute_session(
        self,
        worker: WorkerConfig,
        prompt: str,
        phase: str,
        timeout_seconds: float,
        cancellation: object | None = None,
    ) -> DirectExecuteResult:
        """
        Create a Flocks session, send the Cairn-rendered prompt as a user
        message, run the SessionLoop (which provides tools to the LLM), and
        return the assistant's final response.
        """
        from flocks.storage.storage import Storage
        from flocks.session.session import Session
        from flocks.session.message import Message, MessageRole
        from flocks.session.session_loop import SessionLoop, LoopCallbacks

        await Storage.init()

        # ── 1. Resolve model / provider ──────────────────────────────
        provider_id = worker.env.get("FLOCKS_PROVIDER") or None
        model_id = worker.env.get("FLOCKS_MODEL") or None

        if not model_id or not provider_id:
            from flocks.config.config import Config
            resolved = await Config.resolve_default_llm()
            if resolved:
                provider_id = provider_id or resolved.get("provider_id")
                model_id = model_id or resolved.get("model_id")

        if not model_id or not provider_id:
            msg = (
                "No model/provider configured for flocks worker. "
                "Set FLOCKS_MODEL / FLOCKS_PROVIDER env or configure default_models.llm in flocks.json"
            )
            LOG.error("flocks.execute_direct.no_config phase=%s", phase)
            return DirectExecuteResult(stderr=msg, returncode=1)

        LOG.info(
            "flocks.execute_direct.start phase=%s provider=%s model=%s",
            phase, provider_id, model_id,
        )

        # ── 2. Log the FULL prompt before sending ────────────────────
        self._log_text(f"CAIRN PROMPT phase={phase}", prompt)

        # ── 3. Create Flocks session ─────────────────────────────────
        session = await Session.create(
            project_id="__cairn_dispatcher__",
            directory="/tmp",
            title=f"cairn-{phase}",
            agent=worker.name or "rex",
            model=model_id,
            provider=provider_id,
            model_pinned=True,
            category="task",
            # Disable question permission — non-interactive mode
            permission=[{"permission": "question", "action": "deny", "pattern": "*"}],
        )

        LOG.debug("flocks.session.created id=%s phase=%s agent=%s", session.id, phase, session.agent)

        # ── 4. Send Cairn prompt as user message ─────────────────────
        await Message.create(
            session_id=session.id,
            role=MessageRole.USER,
            content=prompt,
            agent=session.agent or worker.name,
        )

        # ── 5. Run SessionLoop (LLM + tools) ─────────────────────────
        LOG.info("flocks.session_loop.start session=%s phase=%s", session.id, phase)
        try:
            result = await asyncio.wait_for(
                SessionLoop.run(
                    session.id,
                    provider_id=provider_id,
                    model_id=model_id,
                    callbacks=LoopCallbacks(),
                ),
                timeout=timeout_seconds,
            )
        except Exception:
            LOG.exception("flocks.session_loop.error session=%s phase=%s", session.id, phase)
            raise

        LOG.info(
            "flocks.session_loop.done session=%s phase=%s action=%s error=%s",
            session.id, phase, result.action, result.error,
        )

        # ── 6. Extract assistant's final response ────────────────────
        all_messages = await Message.list(session.id)
        assistant_msgs = [m for m in all_messages if getattr(m, "role", None) == "assistant"]
        if assistant_msgs:
            response_text = await Message.get_text_content(assistant_msgs[-1])
        elif result.error:
            response_text = json.dumps({"error": result.error})
        else:
            response_text = ""

        # ── 8. Log the FINAL response ────────────────────────────────
        self._log_text(f"LLM RESPONSE phase={phase} session={session.id}", response_text)

        LOG.info(
            "flocks.execute_direct.complete phase=%s session=%s response_length=%d returncode=%d",
            phase, session.id, len(response_text), 0 if not result.error else 1,
        )

        return DirectExecuteResult(
            stdout=response_text,
            returncode=0 if not result.error else 1,
            session=session.id,
        )

    def extract_response_text(self, stdout: str, stderr: str) -> str:
        """Return stdout as-is (no special extraction needed)."""
        return stdout

    def extract_session(self, session: str | None, stdout: str, stderr: str) -> str | None:
        """Return the session ID passed in or extracted from execution."""
        return session