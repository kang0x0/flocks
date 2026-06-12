from __future__ import annotations

import logging
import time

from flocks.cairn.dispatcher.config import DispatchConfig, WorkerConfig
from flocks.cairn.dispatcher.contracts import parse_json_output, validate_explore_payload
from flocks.cairn.dispatcher.prompting import load_prompt, render_prompt
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
    write_graph_snapshot_local,
    write_graph_snapshot_reference,
)
from flocks.cairn.dispatcher.workers.registry import get_driver
from flocks.cairn.models import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


def run_explore_task(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    export_yaml: str,
    intent: Intent,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    driver = get_driver(worker.type)
    if driver.can_execute_direct():
        return _run_explore_direct(config, client, driver, project, export_yaml, intent, worker, cancellation)
    return _run_explore_container(config, client, container_manager, driver, project, export_yaml, intent, worker, cancellation)


def _run_explore_direct(
    config: DispatchConfig,
    client: CairnClient,
    driver,
    project: ProjectDetail,
    export_yaml: str,
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
            LOG.info("explore cancelled during healthcheck project=%s intent=%s worker=%s reason=%s", project.project.id, intent.id, worker.name, cancelled)
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled"
        if healthcheck.result.returncode != 0:
            LOG.warning("worker unhealthy project=%s intent=%s worker=%s healthcheck_ms=%s stderr=%s", project.project.id, intent.id, worker.name, healthcheck.duration_ms, preview(healthcheck.result.stderr))
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "unhealthy"

        prompt = render_prompt(
            load_prompt(config.runtime.prompt_group, "explore.md"),
            {
                "graph_yaml": write_graph_snapshot_local(export_yaml.strip(), phase="explore_execute"),
                "intent_id": intent.id,
                "intent_description": intent.description,
            },
        )

        # Create Flocks session up-front → frontend can see live chat immediately
        session_id = driver.prepare_session(worker, "explore")
        log_id = record_session_log(
            client, project.project.id, session_id, "explore", worker.name,
            prompt, intent_id=intent.id, status="running",
        )

        execute_started = time.perf_counter()
        first = run_direct_execution(
            driver, worker, prompt,
            phase="explore",
            timeout_seconds=config.tasks.explore.timeout,
            cancellation=cancellation,
            session_id=session_id,
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        cancelled = cancel_reason(first, cancellation)
        if cancelled is not None:
            LOG.info("explore cancelled project=%s intent=%s worker=%s reason=%s execute_ms=%s", project.project.id, intent.id, worker.name, cancelled, execute_ms)
            update_session_log(client, project.project.id, log_id, "cancelled")
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled"
        if not did_timeout(first) and first.returncode == 0:
            try:
                model_output = driver.extract_response_text(first.stdout, first.stderr)
                payload = parse_json_output(model_output)
                kind, description = validate_explore_payload(payload)
            except Exception as exc:
                LOG.warning("explore parse failed project=%s intent=%s worker=%s error=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s", project.project.id, intent.id, worker.name, exc, execute_ms, int((time.perf_counter() - task_started) * 1000), preview(first.stdout), preview(first.stderr))
                update_session_log(client, project.project.id, log_id, "failed")
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "failed"
            if kind == "rejected":
                LOG.warning("explore rejected project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s", project.project.id, intent.id, worker.name, execute_ms, int((time.perf_counter() - task_started) * 1000), preview(first.stdout))
                update_session_log(client, project.project.id, log_id, "rejected")
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "rejected"
            conclude = write_conclude_result_with_fact_id(client, project.project.id, intent.id, worker.name, description, source="explore_execute", phase_ms=execute_ms, total_ms=int((time.perf_counter() - task_started) * 1000))
            update_session_log(client, project.project.id, log_id, conclude.status if conclude.status == "success" else "failed")
            return conclude.status
        if did_timeout(first):
            LOG.warning("explore timed out project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s", project.project.id, intent.id, worker.name, execute_ms, int((time.perf_counter() - task_started) * 1000), preview(first.stdout), preview(first.stderr))
            update_session_log(client, project.project.id, log_id, "timeout")
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "failed"
        LOG.warning("explore command failed project=%s intent=%s worker=%s code=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s", project.project.id, intent.id, worker.name, first.returncode, execute_ms, int((time.perf_counter() - task_started) * 1000), preview(first.stdout), preview(first.stderr))
        update_session_log(client, project.project.id, log_id, "failed")
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    except Exception:
        LOG.exception("explore task crashed project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    finally:
        lease.stop()


def _run_explore_container(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    driver,
    project: ProjectDetail,
    export_yaml: str,
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
            "starting container exec project=%s intent=%s worker=%s phase=explore_healthcheck timeout=%ss",
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
                "explore cancelled during healthcheck project=%s intent=%s worker=%s reason=%s",
                project.project.id,
                intent.id,
                worker.name,
                cancelled,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled"
        if lease.failure is not None:
            LOG.warning(
                "heartbeat lost during explore healthcheck project=%s intent=%s worker=%s status=%s",
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
            load_prompt(config.runtime.prompt_group, "explore.md"),
            {
                "graph_yaml": write_graph_snapshot_reference(
                    container_manager,
                    container_name,
                    export_yaml.strip(),
                    phase="explore_execute",
                ),
                "intent_id": intent.id,
                "intent_description": intent.description,
            },
        )

        session = driver.prepare_session()
        execute = driver.build_execute(worker, prompt, session)
        session = execute.session
        execute_started = time.perf_counter()
        first = _run_process(
            container_manager,
            container_name,
            worker,
            execute.argv,
            phase="explore_execute",
            timeout=config.tasks.explore.timeout,
            lease=lease,
            cancellation=cancellation,
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        session = driver.extract_session(session, first.stdout, first.stderr)
        # Write running log as soon as session_id is known (container path)
        log_id = record_session_log(
            client, project.project.id, session, "explore", worker.name,
            prompt, intent_id=intent.id, status="running",
        )
        cancelled = cancel_reason(first, cancellation)
        if cancelled is not None:
            LOG.info(
                "explore cancelled project=%s intent=%s worker=%s reason=%s execute_ms=%s",
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
                "heartbeat lost during explore project=%s intent=%s worker=%s status=%s execute_ms=%s",
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
                kind, description = validate_explore_payload(payload)
            except Exception as exc:
                LOG.warning(
                    "explore parse failed project=%s intent=%s worker=%s error=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
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
                    project.project.id,
                    intent,
                    export_yaml,
                    session,
                    lease,
                    cancellation,
                )
            if kind == "rejected":
                LOG.warning(
                    "explore rejected project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s",
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
            conclude = write_conclude_result_with_fact_id(
                client,
                project.project.id,
                intent.id,
                worker.name,
                description,
                source="explore_execute",
                phase_ms=execute_ms,
                total_ms=int((time.perf_counter() - task_started) * 1000),
            )
            update_session_log(client, project.project.id, log_id, conclude.status if conclude.status == "success" else "failed")
            return conclude.status
        if did_timeout(first):
            LOG.warning(
                "explore timed out project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                project.project.id,
                intent.id,
                worker.name,
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
                project.project.id,
                intent,
                export_yaml,
                session,
                lease,
                cancellation,
            )
        LOG.warning(
            "explore command failed project=%s intent=%s worker=%s code=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            first.returncode,
            execute_ms,
            int((time.perf_counter() - task_started) * 1000),
            preview(first.stdout),
            preview(first.stderr),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    except Exception:
        LOG.exception("explore task crashed project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
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
    project_id: str,
    intent: Intent,
    export_yaml: str,
    session: str | None,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
) -> str:
    if not driver.supports_conclude() or not session:
        LOG.info(
            "conclude fallback unavailable project=%s intent=%s worker=%s supports_conclude=%s has_session=%s",
            project_id,
            intent.id,
            worker.name,
            driver.supports_conclude(),
            bool(session),
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"
    if lease.failure is not None:
        LOG.warning("conclude fallback skipped because heartbeat already lost project=%s intent=%s worker=%s", project_id, intent.id, worker.name)
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"
    if cancellation.is_cancelled:
        LOG.info(
            "conclude fallback skipped because task was cancelled project=%s intent=%s worker=%s reason=%s",
            project_id,
            intent.id,
            worker.name,
            cancellation.reason,
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        return "cancelled"

    if not project_allows_conclude_fallback(
        client,
        project_id,
        worker_name=worker.name,
        intent_id=intent.id,
    ):
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"

    container_name = container_manager.ensure_running(project_id)

    prompt = render_prompt(
        load_prompt(config.runtime.prompt_group, "explore_conclude.md"),
        {
            "graph_yaml": write_graph_snapshot_reference(
                container_manager,
                container_name,
                export_yaml.strip(),
                phase="explore_conclude",
            ),
            "intent_id": intent.id,
            "intent_description": intent.description,
        },
    )
    conclude_argv = driver.build_conclude(worker, prompt, session)
    LOG.info("starting conclude fallback project=%s intent=%s worker=%s", project_id, intent.id, worker.name)
    conclude_started = time.perf_counter()
    result = _run_process(
        container_manager,
        container_name,
        worker,
        conclude_argv,
        phase="explore_conclude",
        timeout=config.tasks.explore.conclude_timeout,
        lease=lease,
        cancellation=cancellation,
    )
    conclude_ms = int((time.perf_counter() - conclude_started) * 1000)
    cancelled = cancel_reason(result, cancellation)
    if cancelled is not None:
        LOG.info(
            "conclude cancelled project=%s intent=%s worker=%s reason=%s conclude_ms=%s",
            project_id,
            intent.id,
            worker.name,
            cancelled,
            conclude_ms,
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        return "cancelled"
    if lease.failure is not None:
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"
    if result.timed_out or result.returncode != 0:
        LOG.warning(
            "conclude failed project=%s intent=%s worker=%s code=%s timed_out=%s conclude_ms=%s stdout_preview=%s stderr_preview=%s",
            project_id,
            intent.id,
            worker.name,
            result.returncode,
            result.timed_out,
            conclude_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"
    try:
        model_output = driver.extract_response_text(result.stdout, result.stderr)
        payload = parse_json_output(model_output)
        kind, description = validate_explore_payload(payload)
    except Exception as exc:
        LOG.warning(
            "conclude parse failed project=%s intent=%s worker=%s error=%s conclude_ms=%s stdout_preview=%s stderr_preview=%s",
            project_id,
            intent.id,
            worker.name,
            exc,
            conclude_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"
    if kind == "rejected":
        LOG.warning(
            "conclude rejected project=%s intent=%s worker=%s conclude_ms=%s stdout_preview=%s",
            project_id,
            intent.id,
            worker.name,
            conclude_ms,
            preview(result.stdout),
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        return "rejected"
    return write_conclude_result(
        client,
        project_id,
        intent.id,
        worker.name,
        description,
        source="explore_conclude",
        phase_ms=conclude_ms,
    )


def _run_process(
    container_manager: ContainerManager,
    container_name: str,
    worker: WorkerConfig,
    argv: list[str],
    *,
    phase: str,
    timeout: int,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
):
    return run_worker_process(
        container_manager,
        container_name,
        worker,
        argv,
        phase=phase,
        timeout_seconds=timeout,
        lease=lease,
        cancellation=cancellation,
    )