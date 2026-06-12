from __future__ import annotations

import logging
import time

from flocks.cairn.dispatcher.config import DispatchConfig, WorkerConfig
from flocks.cairn.dispatcher.contracts import (
    parse_json_output,
    validate_bootstrap_conclude_payload,
    validate_bootstrap_execute_payload,
)
from flocks.cairn.dispatcher.prompting import format_hints, load_prompt, render_prompt
from flocks.cairn.dispatcher.protocol.client import CairnClient
from flocks.cairn.dispatcher.runtime.cancellation import TaskCancellation
from flocks.cairn.dispatcher.runtime.containers import ContainerManager
from flocks.cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from flocks.cairn.dispatcher.tasks.common import (
    best_effort_release,
    cancel_reason,
    did_timeout,
    preview,
    project_allows_conclude_fallback,
    record_session_log,
    run_direct_execution,
    run_direct_healthcheck,
    run_healthcheck,
    run_worker_process,
    update_session_log,
    write_conclude_result,
    write_conclude_result_with_fact_id,
)
from flocks.cairn.dispatcher.workers.base import WorkerDriver
from flocks.cairn.dispatcher.workers.registry import get_driver
from flocks.cairn.models import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


def run_bootstrap_task(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    intent: Intent,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    driver = get_driver(worker.type)
    if driver.can_execute_direct():
        return _run_bootstrap_direct(config, client, driver, project, intent, worker, cancellation)
    return _run_bootstrap_container(config, client, container_manager, driver, project, intent, worker, cancellation)


def _run_bootstrap_direct(
    config: DispatchConfig,
    client: CairnClient,
    driver: WorkerDriver,
    project: ProjectDetail,
    intent: Intent,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    task_started = time.perf_counter()
    healthcheck_timeout = config.runtime.healthcheck_timeout
    lease = HeartbeatLease.for_intent(client, project.project.id, intent.id, worker.name, config.runtime.interval)
    lease.start()
    try:
        healthcheck = run_direct_healthcheck(
            driver,
            worker,
            timeout_seconds=healthcheck_timeout,
            cancellation=cancellation,
        )
        cancelled = cancel_reason(healthcheck.result, cancellation)
        if cancelled is not None:
            LOG.info("bootstrap cancelled during healthcheck project=%s intent=%s worker=%s reason=%s", project.project.id, intent.id, worker.name, cancelled)
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled"
        if healthcheck.result.returncode != 0:
            LOG.warning("worker unhealthy project=%s intent=%s worker=%s healthcheck_ms=%s stderr=%s", project.project.id, intent.id, worker.name, healthcheck.duration_ms, preview(healthcheck.result.stderr))
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "unhealthy"

        prompt = render_prompt(
            load_prompt(config.runtime.prompt_group, "bootstrap.md"),
            _bootstrap_prompt_replacements(project),
        )

        # Create Flocks session up-front → frontend can see live chat immediately
        session_id = driver.prepare_session(worker, "bootstrap")
        log_id = record_session_log(
            client, project.project.id, session_id, "bootstrap", worker.name,
            prompt, intent_id=intent.id, status="running",
        )

        execute_started = time.perf_counter()
        first = run_direct_execution(
            driver, worker, prompt,
            phase="bootstrap",
            timeout_seconds=config.tasks.bootstrap.timeout,
            cancellation=cancellation,
            session_id=session_id,
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        cancelled = cancel_reason(first, cancellation)
        if cancelled is not None:
            LOG.info("bootstrap cancelled project=%s intent=%s worker=%s reason=%s execute_ms=%s", project.project.id, intent.id, worker.name, cancelled, execute_ms)
            update_session_log(client, project.project.id, log_id, "cancelled")
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled"
        if not did_timeout(first) and first.returncode == 0:
            try:
                model_output = driver.extract_response_text(first.stdout, first.stderr)
                payload = parse_json_output(model_output)
                kind, data = validate_bootstrap_execute_payload(payload)
            except Exception as exc:
                LOG.warning("bootstrap parse failed project=%s intent=%s worker=%s error=%s execute_ms=%s total_ms=%s — falling back to conclude", project.project.id, intent.id, worker.name, exc, execute_ms, int((time.perf_counter() - task_started) * 1000))
                return _run_bootstrap_conclude_direct(
                    config, client, driver, project, intent, worker,
                    session_id, lease, cancellation, prompt,
                    execute_ms=execute_ms, total_ms=int((time.perf_counter() - task_started) * 1000),
                    log_id=log_id,
                )
            if kind == "rejected":
                LOG.warning("bootstrap rejected project=%s intent=%s worker=%s execute_ms=%s", project.project.id, intent.id, worker.name, execute_ms)
                update_session_log(client, project.project.id, log_id, "rejected")
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "rejected"
            return _write_bootstrap_complete_result(
                client, project.project.id, intent.id, worker.name,
                data["fact_description"], data["complete_description"],
                source="bootstrap", phase_ms=execute_ms,
                total_ms=int((time.perf_counter() - task_started) * 1000),
                session_id=session_id, prompt=prompt, log_id=log_id,
            )
        if did_timeout(first):
            LOG.warning("bootstrap timed out project=%s intent=%s worker=%s execute_ms=%s — falling back to conclude", project.project.id, intent.id, worker.name, execute_ms)
            return _run_bootstrap_conclude_direct(
                config, client, driver, project, intent, worker,
                session_id, lease, cancellation, prompt,
                execute_ms=execute_ms, total_ms=int((time.perf_counter() - task_started) * 1000),
                log_id=log_id,
            )
        LOG.warning("bootstrap command failed project=%s intent=%s worker=%s code=%s execute_ms=%s", project.project.id, intent.id, worker.name, first.returncode, execute_ms)
        update_session_log(client, project.project.id, log_id, "failed")
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    except Exception:
        LOG.exception("bootstrap task crashed project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    finally:
        lease.stop()


def _run_bootstrap_container(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    driver: WorkerDriver,
    project: ProjectDetail,
    intent: Intent,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    task_started = time.perf_counter()
    healthcheck_timeout = config.runtime.healthcheck_timeout
    lease = HeartbeatLease.for_intent(client, project.project.id, intent.id, worker.name, config.runtime.interval)
    lease.start()
    try:
        container_name = container_manager.ensure_running(project.project.id)

        LOG.info(
            "starting container exec project=%s intent=%s worker=%s phase=bootstrap_healthcheck timeout=%ss",
            project.project.id,
            intent.id,
            worker.name,
            healthcheck_timeout,
        )
        healthcheck = run_healthcheck(
            container_manager,
            container_name,
            worker,
            driver.build_healthcheck(worker),
            timeout_seconds=healthcheck_timeout,
            lease=lease,
            cancellation=cancellation,
        )
        cancelled = cancel_reason(healthcheck.result, cancellation)
        if cancelled is not None:
            LOG.info(
                "bootstrap cancelled during healthcheck project=%s intent=%s worker=%s reason=%s",
                project.project.id,
                intent.id,
                worker.name,
                cancelled,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled"
        if lease.failure is not None:
            LOG.warning(
                "heartbeat lost during bootstrap healthcheck project=%s intent=%s worker=%s status=%s",
                project.project.id,
                intent.id,
                worker.name,
                lease.failure.status_code,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "failed"
        if healthcheck.result.returncode != 0:
            LOG.warning(
                "worker unhealthy project=%s intent=%s worker=%s healthcheck_ms=%s stderr=%s",
                project.project.id,
                intent.id,
                worker.name,
                healthcheck.duration_ms,
                preview(healthcheck.result.stderr),
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "unhealthy"

        prompt = render_prompt(
            load_prompt(config.runtime.prompt_group, "bootstrap.md"),
            _bootstrap_prompt_replacements(project),
        )

        session = driver.prepare_session()
        execute = driver.build_execute(worker, prompt, session)
        session = execute.session
        execute_started = time.perf_counter()
        first = run_worker_process(
            container_manager,
            container_name,
            worker,
            execute.argv,
            phase="bootstrap",
            timeout_seconds=config.tasks.bootstrap.timeout,
            lease=lease,
            cancellation=cancellation,
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        session = driver.extract_session(session, first.stdout, first.stderr)
        # Write running log as soon as session_id is known (container path)
        log_id = record_session_log(
            client, project.project.id, session, "bootstrap", worker.name,
            prompt, intent_id=intent.id, status="running",
        )
        cancelled = cancel_reason(first, cancellation)
        if cancelled is not None:
            LOG.info(
                "bootstrap cancelled project=%s intent=%s worker=%s reason=%s execute_ms=%s",
                project.project.id,
                intent.id,
                worker.name,
                cancelled,
                execute_ms,
            )
            update_session_log(client, project.project.id, log_id, "cancelled")
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled"
        if lease.failure is not None:
            LOG.warning(
                "heartbeat lost during bootstrap project=%s intent=%s worker=%s status=%s execute_ms=%s",
                project.project.id,
                intent.id,
                worker.name,
                lease.failure.status_code,
                execute_ms,
            )
            update_session_log(client, project.project.id, log_id, "failed")
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "failed"
        if not did_timeout(first) and first.returncode == 0:
            try:
                model_output = driver.extract_response_text(first.stdout, first.stderr)
                payload = parse_json_output(model_output)
                kind, data = validate_bootstrap_execute_payload(payload)
            except Exception as exc:
                LOG.warning(
                    "bootstrap parse failed project=%s intent=%s worker=%s error=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                    project.project.id,
                    intent.id,
                    worker.name,
                    exc,
                    execute_ms,
                    int((time.perf_counter() - task_started) * 1000),
                    preview(first.stdout),
                    preview(first.stderr),
                )
                return _try_conclude_fallback(
                    config,
                    client,
                    container_manager,
                    container_name,
                    worker,
                    driver,
                    project,
                    intent,
                    session,
                    lease,
                    cancellation,
                )
            if kind == "rejected":
                LOG.warning(
                    "bootstrap rejected project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s",
                    project.project.id,
                    intent.id,
                    worker.name,
                    execute_ms,
                    int((time.perf_counter() - task_started) * 1000),
                    preview(first.stdout),
                )
                update_session_log(client, project.project.id, log_id, "rejected")
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "rejected"
            return _write_bootstrap_complete_result(
                client,
                project.project.id,
                intent.id,
                worker.name,
                data["fact_description"],
                data["complete_description"],
                source="bootstrap",
                phase_ms=execute_ms,
                total_ms=int((time.perf_counter() - task_started) * 1000),
                session_id=session,
                prompt=prompt,
                log_id=log_id,
            )
        if did_timeout(first):
            LOG.warning(
                "bootstrap timed out project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                project.project.id,
                intent.id,
                worker.name,
                execute_ms,
                int((time.perf_counter() - task_started) * 1000),
                preview(first.stdout),
                preview(first.stderr),
            )
            update_session_log(client, project.project.id, log_id, "timeout")
            return _try_conclude_fallback(
                config,
                client,
                container_manager,
                container_name,
                worker,
                driver,
                project,
                intent,
                session,
                lease,
                cancellation,
            )
        LOG.warning(
            "bootstrap command failed project=%s intent=%s worker=%s code=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            first.returncode,
            execute_ms,
            int((time.perf_counter() - task_started) * 1000),
            preview(first.stdout),
            preview(first.stderr),
        )
        update_session_log(client, project.project.id, log_id, "failed")
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    except Exception:
        LOG.exception("bootstrap task crashed project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    finally:
        lease.stop()


def _try_conclude_fallback(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    container_name: str,
    worker: WorkerConfig,
    driver,
    project: ProjectDetail,
    intent: Intent,
    session: str | None,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
) -> str:
    if not driver.supports_conclude() or not session:
        LOG.info(
            "bootstrap conclude fallback unavailable project=%s intent=%s worker=%s supports_conclude=%s has_session=%s",
            project.project.id,
            intent.id,
            worker.name,
            driver.supports_conclude(),
            bool(session),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    if lease.failure is not None:
        LOG.warning(
            "bootstrap conclude fallback skipped because heartbeat already lost project=%s intent=%s worker=%s",
            project.project.id,
            intent.id,
            worker.name,
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    if cancellation.is_cancelled:
        LOG.info(
            "bootstrap conclude fallback skipped because task was cancelled project=%s intent=%s worker=%s reason=%s",
            project.project.id,
            intent.id,
            worker.name,
            cancellation.reason,
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "cancelled"

    if not project_allows_conclude_fallback(
        client,
        project.project.id,
        worker_name=worker.name,
        intent_id=intent.id,
    ):
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"

    container_name = container_manager.ensure_running(project.project.id)

    prompt = render_prompt(
        load_prompt(config.runtime.prompt_group, "bootstrap_conclude.md"),
        _bootstrap_prompt_replacements(project),
    )
    conclude_argv = driver.build_conclude(worker, prompt, session)
    LOG.info("starting bootstrap conclude fallback project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
    conclude_started = time.perf_counter()
    result = run_worker_process(
        container_manager,
        container_name,
        worker,
        conclude_argv,
        phase="bootstrap_conclude",
        timeout_seconds=config.tasks.bootstrap.conclude_timeout,
        lease=lease,
        cancellation=cancellation,
    )
    conclude_ms = int((time.perf_counter() - conclude_started) * 1000)
    cancelled = cancel_reason(result, cancellation)
    if cancelled is not None:
        LOG.info(
            "bootstrap conclude cancelled project=%s intent=%s worker=%s reason=%s conclude_ms=%s",
            project.project.id,
            intent.id,
            worker.name,
            cancelled,
            conclude_ms,
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "cancelled"
    if lease.failure is not None:
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    if result.timed_out or result.returncode != 0:
        LOG.warning(
            "bootstrap conclude failed project=%s intent=%s worker=%s code=%s timed_out=%s conclude_ms=%s stdout_preview=%s stderr_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            result.returncode,
            result.timed_out,
            conclude_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    try:
        model_output = driver.extract_response_text(result.stdout, result.stderr)
        payload = parse_json_output(model_output)
        conclude_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(conclude_data, dict) and isinstance(conclude_data.get("complete"), dict):
            LOG.warning(
                "bootstrap conclude returned unexpected complete payload project=%s intent=%s worker=%s complete_preview=%s",
                project.project.id,
                intent.id,
                worker.name,
                preview(str(conclude_data.get("complete"))),
            )
        kind, fact_description = validate_bootstrap_conclude_payload(payload)
    except Exception as exc:
        LOG.warning(
            "bootstrap conclude parse failed project=%s intent=%s worker=%s error=%s conclude_ms=%s stdout_preview=%s stderr_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            exc,
            conclude_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    if kind == "rejected":
        LOG.warning(
            "bootstrap conclude rejected project=%s intent=%s worker=%s conclude_ms=%s stdout_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            conclude_ms,
            preview(result.stdout),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "rejected"
    return write_conclude_result(
        client,
        project.project.id,
        intent.id,
        worker.name,
        fact_description,
        source="bootstrap_conclude",
        phase_ms=conclude_ms,
    )


def _run_bootstrap_conclude_direct(
    config: DispatchConfig,
    client: CairnClient,
    driver: WorkerDriver,
    project: ProjectDetail,
    intent: Intent,
    worker: WorkerConfig,
    session_id: str | None,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
    prompt: str,
    *,
    execute_ms: int,
    total_ms: int,
    log_id: str | None = None,
) -> str:
    """Conclude fallback for the direct-execution path.
    
    When bootstrap parse fails or times out, send the ``bootstrap_conclude.md``
    prompt as a follow-up message in the same session to extract a fact.
    Mirrors how ``_try_conclude_fallback`` works for the container path.
    """
    pid = project.project.id
    if not driver.supports_conclude() or not session_id:
        LOG.info(
            "bootstrap conclude fallback unavailable (direct) project=%s intent=%s worker=%s supports_conclude=%s has_session=%s",
            pid, intent.id, worker.name,
            driver.supports_conclude(), bool(session_id),
        )
        update_session_log(client, pid, log_id, "failed")
        best_effort_release(client, pid, intent.id, worker.name)
        return "failed"
    if lease.failure is not None:
        LOG.warning(
            "bootstrap conclude fallback skipped (direct) because heartbeat already lost project=%s intent=%s worker=%s",
            pid, intent.id, worker.name,
        )
        update_session_log(client, pid, log_id, "failed")
        best_effort_release(client, pid, intent.id, worker.name)
        return "failed"
    if cancellation.is_cancelled:
        LOG.info(
            "bootstrap conclude fallback skipped (direct) because task was cancelled project=%s intent=%s worker=%s reason=%s",
            pid, intent.id, worker.name, cancellation.reason,
        )
        best_effort_release(client, pid, intent.id, worker.name)
        return "cancelled"

    if not project_allows_conclude_fallback(
        client, pid,
        worker_name=worker.name, intent_id=intent.id,
    ):
        update_session_log(client, pid, log_id, "failed")
        best_effort_release(client, pid, intent.id, worker.name)
        return "failed"

    conclude_prompt = render_prompt(
        load_prompt(config.runtime.prompt_group, "bootstrap_conclude.md"),
        _bootstrap_prompt_replacements(project),
    )
    LOG.info("starting bootstrap conclude fallback (direct) project=%s intent=%s worker=%s session=%s", pid, intent.id, worker.name, session_id)
    conclude_started = time.perf_counter()
    try:
        result = driver.conclude_direct(
            worker,
            conclude_prompt,
            session_id,
            phase="bootstrap_conclude",
            timeout_seconds=config.tasks.bootstrap.conclude_timeout,
            cancellation=cancellation,
        )
    except Exception as exc:
        LOG.exception("bootstrap conclude fallback crashed (direct) project=%s intent=%s worker=%s", pid, intent.id, worker.name)
        update_session_log(client, pid, log_id, "failed")
        best_effort_release(client, pid, intent.id, worker.name)
        return "failed"

    conclude_ms = int((time.perf_counter() - conclude_started) * 1000)
    cancelled = cancel_reason(result, cancellation)
    if cancelled is not None:
        LOG.info("bootstrap conclude cancelled (direct) project=%s intent=%s worker=%s reason=%s conclude_ms=%s", pid, intent.id, worker.name, cancelled, conclude_ms)
        best_effort_release(client, pid, intent.id, worker.name)
        return "cancelled"
    if lease.failure is not None:
        update_session_log(client, pid, log_id, "failed")
        best_effort_release(client, pid, intent.id, worker.name)
        return "failed"
    if result.timed_out or result.returncode != 0:
        LOG.warning("bootstrap conclude failed (direct) project=%s intent=%s worker=%s code=%s timed_out=%s conclude_ms=%s", pid, intent.id, worker.name, result.returncode, result.timed_out, conclude_ms)
        update_session_log(client, pid, log_id, "failed")
        best_effort_release(client, pid, intent.id, worker.name)
        return "failed"
    try:
        model_output = driver.extract_response_text(result.stdout, result.stderr)
        payload = parse_json_output(model_output)
        conclude_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(conclude_data, dict) and isinstance(conclude_data.get("complete"), dict):
            LOG.warning("bootstrap conclude returned unexpected complete payload (direct) project=%s intent=%s worker=%s complete_preview=%s", pid, intent.id, worker.name, preview(str(conclude_data.get("complete"))))
        kind, fact_description = validate_bootstrap_conclude_payload(payload)
    except Exception as exc:
        LOG.warning("bootstrap conclude parse failed (direct) project=%s intent=%s worker=%s error=%s conclude_ms=%s", pid, intent.id, worker.name, exc, conclude_ms)
        update_session_log(client, pid, log_id, "failed")
        best_effort_release(client, pid, intent.id, worker.name)
        return "failed"
    if kind == "rejected":
        LOG.warning("bootstrap conclude rejected (direct) project=%s intent=%s worker=%s conclude_ms=%s", pid, intent.id, worker.name, conclude_ms)
        best_effort_release(client, pid, intent.id, worker.name)
        return "rejected"
    update_session_log(client, pid, log_id, "success")
    return write_conclude_result(
        client, pid, intent.id, worker.name,
        fact_description,
        source="bootstrap_conclude",
        phase_ms=conclude_ms,
    )


def _bootstrap_prompt_replacements(project: ProjectDetail) -> dict[str, str]:
    facts = {fact.id: fact.description for fact in project.facts}
    hints = [
        {
            "id": hint.id,
            "content": hint.content,
            "creator": hint.creator,
            "created_at": hint.created_at,
        }
        for hint in project.hints
    ]
    return {
        "origin": facts.get("origin", ""),
        "goal": facts.get("goal", ""),
        "hints": format_hints(hints),
    }


def _write_bootstrap_complete_result(
    client: CairnClient,
    project_id: str,
    intent_id: str,
    worker_name: str,
    fact_description: str,
    complete_description: str,
    *,
    source: str,
    phase_ms: int,
    total_ms: int | None = None,
    session_id: str | None = None,
    prompt: str | None = None,
    log_id: str | None = None,
) -> str:
    conclude = write_conclude_result_with_fact_id(
        client,
        project_id,
        intent_id,
        worker_name,
        fact_description,
        source=source,
        phase_ms=phase_ms,
        total_ms=total_ms,
    )
    if conclude.status != "success":
        update_session_log(client, project_id, log_id, "failed")
        return "failed"
    if conclude.fact_id is None:
        LOG.warning(
            "bootstrap complete deferred because conclude response omitted fact id project=%s intent=%s worker=%s source=%s",
            project_id, intent_id, worker_name, source,
        )
        update_session_log(client, project_id, log_id, "success")
        return "success"

    fact_ids = [conclude.fact_id]
    response = client.complete(project_id, fact_ids, complete_description, worker_name)
    if response.status_code in (403, 409):
        LOG.info(
            "bootstrap complete deferred project=%s intent=%s worker=%s source=%s status=%s fact_id=%s",
            project_id, intent_id, worker_name, source, response.status_code, conclude.fact_id,
        )
        update_session_log(client, project_id, log_id, "success")
        return "success"
    if not response.ok:
        LOG.warning(
            "bootstrap complete write failed project=%s intent=%s worker=%s source=%s fact_id=%s status=%s body=%s",
            project_id, intent_id, worker_name, source, conclude.fact_id, response.status_code, response.text,
        )
        update_session_log(client, project_id, log_id, "success")
        return "success"
    if total_ms is None:
        LOG.info(
            "bootstrap completed project=%s intent=%s worker=%s source=%s from=%s phase_ms=%s",
            project_id, intent_id, worker_name, source, [conclude.fact_id], phase_ms,
        )
    else:
        LOG.info(
            "bootstrap completed project=%s intent=%s worker=%s source=%s from=%s phase_ms=%s total_ms=%s",
            project_id, intent_id, worker_name, source, [conclude.fact_id], phase_ms, total_ms,
        )
    update_session_log(client, project_id, log_id, "success")
    return "success"