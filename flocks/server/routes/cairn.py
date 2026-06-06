"""Cairn collaboration protocol — FastAPI routes.

Merged from original Cairn routers (projects, hints, intents, export, settings).
All endpoints are under /api/cairn prefix.
Uses module-level storage functions from flocks.cairn.storage.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import logging

from datetime import datetime

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from flocks.cairn.dispatcher.scheduler.loop import DispatcherLoop
from flocks.cairn.dispatcher.debug_log import is_debug_log_enabled, set_debug_log_enabled
from flocks.cairn.models import (
    CompleteRequest,
    ConcludeRequest,
    ConcludeResponse,
    CreateHintRequest,
    CreateIntentRequest,
    CreateProjectRequest,
    Fact,
    HeartbeatRequest,
    Hint,
    Intent,
    ProjectDetail,
    ProjectMeta,
    ProjectReason,
    ProjectSummary,
    ReasonClaimRequest,
    ReopenRequest,
    ReopenResponse,
    Settings,
    UpdateProjectStatusRequest,
    UpdateProjectTitleRequest,
)
from flocks.cairn.storage import (
    build_intents,
    check_project_active,
    check_project_completed,
    check_project_hint_writable,
    clear_project_reason,
    expire_reason_leases,
    expire_workers,
    get_claimable_open_intent_or_404,
    get_completion_intent_or_409,
    get_conn,
    get_project_or_404,
    get_releasable_open_intent_or_404,
    get_settings,
    intent_to_model,
    list_session_ids_for_project,
    list_session_logs,
    list_session_logs_by_intent,
    list_session_logs_by_fact,
    next_fact_id,
    next_hint_id,
    next_intent_id,
    next_project_id,
    project_meta_from_row,
    project_reason_from_row,
    update_settings,
    utcnow,
    validate_facts_exist,
    validate_goal_not_in_sources,
    validate_intent_creator_worker,
)

_DEFAULT_DISPATCHER_YAML = """
server: http://localhost:8000
runtime:
  max_workers: 2
  max_running_projects: 2
  max_project_workers: 1
  interval: 5
  healthcheck_timeout: 15
  prompt_group: default
tasks:
  bootstrap:
    timeout: 120
    conclude_timeout: 60
  reason:
    timeout: 180
    max_intents: 3
  explore:
    timeout: 300
    conclude_timeout: 120
container: null
common_env: {}
workers:
  - name: flocks-worker
    type: flocks
    task_types: [bootstrap, reason, explore]
    max_running: 2
    priority: 0
    env: {}
"""

_dispatcher_state: dict = {
    "thread": None,
    "stop_event": None,
    "loop": None,
}


def _get_dispatcher_config_path() -> Path:
    config_dir = Path.home() / ".flocks" / "cairn"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "dispatcher.yaml"
    if not config_path.exists():
        config_path.write_text(_DEFAULT_DISPATCHER_YAML, encoding="utf-8")
    return config_path


def _run_dispatcher(config_path: Path, stop_event: threading.Event):
    LOG = logging.getLogger("flocks.cairn.dispatcher")
    LOG.info("dispatcher.starting config_path=%s", config_path)
    try:
        loop = DispatcherLoop(config_path)
    except Exception as exc:
        LOG.exception("dispatcher.init_failed config_path=%s", config_path)
        return
    _dispatcher_state["loop"] = loop
    try:
        loop._startup_healthchecks_checked = True  # skip health checks for in-process mode
        LOG.info("dispatcher.started config_path=%s", config_path)
        while not stop_event.is_set():
            try:
                loop._reap_futures()
                loop._reap_cleanup_futures()
                summaries = loop.client.list_projects()
                loop._initialize_reason_checkpoints(summaries)
                loop._refresh_runtime_projects(summaries)
                loop._cancel_inactive_tasks(summaries)
                loop._queue_container_cleanups(summaries)
                loop._dispatch_available(summaries)
            except Exception:
                if stop_event.is_set():
                    break
                LOG.warning("dispatcher.loop_error", exc_info=True)
                time.sleep(5)
                continue
            if stop_event.is_set():
                break
            stop_event.wait(loop.config.runtime.interval)
    except Exception:
        LOG.exception("dispatcher.crashed config_path=%s", config_path)
        pass
    finally:
        loop.close()
        _dispatcher_state["loop"] = None
        _dispatcher_state["thread"] = None
        _dispatcher_state["stop_event"] = None
        LOG.info("dispatcher.stopped")


router = APIRouter(prefix="/api/cairn", tags=["Cairn"])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=Settings)
def handle_get_settings():
    with get_conn() as conn:
        return get_settings(conn)


@router.put("/settings", response_model=Settings)
def handle_update_settings(body: Settings):
    with get_conn() as conn:
        update_settings(conn, body.intent_timeout, body.reason_timeout)
    return body


# ---------------------------------------------------------------------------
# Debug log toggle
# ---------------------------------------------------------------------------


@router.get("/debug-log")
def handle_get_debug_log():
    return {"enabled": is_debug_log_enabled()}


@router.put("/debug-log")
def handle_set_debug_log(body: dict):
    set_debug_log_enabled(body.get("enabled", False))
    return {"enabled": is_debug_log_enabled()}


# ---------------------------------------------------------------------------
# Projects — list / create / get / delete
# ---------------------------------------------------------------------------

@router.get("/projects", response_model=list[ProjectSummary])
def list_projects():
    with get_conn() as conn:
        expire_workers(conn)
        expire_reason_leases(conn)
        rows = conn.execute("""
            SELECT p.*,
                (SELECT COUNT(*) FROM facts WHERE project_id = p.id) AS fact_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id) AS intent_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NOT NULL) AS working_intent_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NULL) AS unclaimed_intent_count,
                (SELECT COUNT(*) FROM hints WHERE project_id = p.id) AS hint_count
            FROM projects p
            ORDER BY p.created_at
        """).fetchall()
        return [
            ProjectSummary(
                id=row["id"],
                title=row["title"],
                status=row["status"],
                created_at=row["created_at"],
                reason=project_reason_from_row(row),
                fact_count=row["fact_count"],
                intent_count=row["intent_count"],
                working_intent_count=row["working_intent_count"],
                unclaimed_intent_count=row["unclaimed_intent_count"],
                hint_count=row["hint_count"],
            )
            for row in rows
        ]


@router.post("/projects", response_model=ProjectDetail, status_code=201)
def create_project(body: CreateProjectRequest):
    with get_conn() as conn:
        pid = next_project_id(conn)
        now = utcnow()

        conn.execute(
            "INSERT INTO projects (id, title, status, created_at) VALUES (?, ?, 'active', ?)",
            (pid, body.title, now),
        )
        conn.execute(
            "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
            ("origin", pid, body.origin),
        )
        conn.execute(
            "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
            ("goal", pid, body.goal),
        )

        hints = []
        if body.hints:
            for h in body.hints:
                hid = next_hint_id(conn, pid)
                conn.execute(
                    "INSERT INTO hints (id, project_id, content, creator, created_at) VALUES (?, ?, ?, ?, ?)",
                    (hid, pid, h.content, h.creator, now),
                )
                hints.append(Hint(id=hid, content=h.content, creator=h.creator, created_at=now))

        return ProjectDetail(
            project=ProjectMeta(id=pid, title=body.title, status="active", created_at=now, reason=None),
            facts=[
                Fact(id="origin", description=body.origin),
                Fact(id="goal", description=body.goal),
            ],
            intents=[],
            hints=hints,
        )


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str):
    with get_conn() as conn:
        expire_workers(conn, project_id)
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)

        facts = conn.execute(
            "SELECT * FROM facts WHERE project_id = ?", (project_id,)
        ).fetchall()
        hints = conn.execute(
            "SELECT * FROM hints WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()

        return ProjectDetail(
            project=project_meta_from_row(row),
            facts=[Fact(**dict(f)) for f in facts],
            intents=build_intents(conn, project_id),
            hints=[Hint(**dict(h)) for h in hints],
        )


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str):
    """Delete a Cairn project and cascade-delete its associated Flocks sessions."""
    import asyncio
    from flocks.session.session import Session

    # 1. Collect Flocks session IDs before deleting the Cairn project
    session_ids: list[str] = []
    with get_conn() as conn:
        get_project_or_404(conn, project_id)
        session_ids = list_session_ids_for_project(conn, project_id)

    # 2. Delete the project from Cairn DB (CASCADE handles worker_session_logs etc.)
    with get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # 3. Delete associated Flocks sessions
    if session_ids:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        for sid in session_ids:
            try:
                loop.run_until_complete(Session.delete("__cairn_dispatcher__", sid))
            except Exception:
                logging.getLogger(__name__).warning(
                    "Failed to delete Flocks session project=%s session=%s", project_id, sid
                )


# ---------------------------------------------------------------------------
# Project title / status
# ---------------------------------------------------------------------------

@router.put("/projects/{project_id}/title", response_model=ProjectMeta)
def update_project_title(project_id: str, body: UpdateProjectTitleRequest):
    with get_conn() as conn:
        get_project_or_404(conn, project_id)
        conn.execute(
            "UPDATE projects SET title = ? WHERE id = ?",
            (body.title, project_id),
        )
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return project_meta_from_row(updated)


@router.put("/projects/{project_id}/status", response_model=ProjectMeta)
def update_project_status(project_id: str, body: UpdateProjectStatusRequest):
    with get_conn() as conn:
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)
        current_status = row["status"]
        if current_status == "completed":
            raise HTTPException(409, "Completed projects cannot change status")
        if current_status == body.status:
            return project_meta_from_row(row)

        conn.execute(
            "UPDATE projects SET status = ? WHERE id = ?",
            (body.status, project_id),
        )
        if body.status == "stopped":
            conn.execute(
                "UPDATE intents SET worker = NULL WHERE project_id = ? AND concluded_at IS NULL",
                (project_id,),
            )
            clear_project_reason(conn, project_id)
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return project_meta_from_row(updated)


# ---------------------------------------------------------------------------
# Reason claim / heartbeat / release
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/reason/claim", response_model=ProjectMeta)
def claim_project_reason(project_id: str, body: ReasonClaimRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)
        current_worker = row["reason_worker"]
        if current_worker is not None and current_worker != body.worker:
            raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
        if current_worker == body.worker:
            return project_meta_from_row(row)

        now = utcnow()
        conn.execute(
            """
            UPDATE projects
            SET reason_worker = ?,
                reason_trigger = ?,
                reason_started_at = ?,
                reason_last_heartbeat_at = ?
            WHERE id = ?
            """,
            (body.worker, body.trigger, now, now, project_id),
        )
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return project_meta_from_row(updated)


@router.post("/projects/{project_id}/reason/heartbeat", response_model=ProjectMeta)
def heartbeat_project_reason(project_id: str, body: HeartbeatRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)
        current_worker = row["reason_worker"]
        if current_worker is None:
            raise HTTPException(409, "Project reason is not currently claimed")
        if current_worker != body.worker:
            raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")

        now = utcnow()
        conn.execute(
            "UPDATE projects SET reason_last_heartbeat_at = ? WHERE id = ?",
            (now, project_id),
        )
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return project_meta_from_row(updated)


@router.post("/projects/{project_id}/reason/release", response_model=ProjectMeta)
def release_project_reason(project_id: str, body: HeartbeatRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)
        current_worker = row["reason_worker"]
        if current_worker is None:
            return project_meta_from_row(row)
        if current_worker != body.worker:
            raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")

        clear_project_reason(conn, project_id)
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return project_meta_from_row(updated)


# ---------------------------------------------------------------------------
# Hints
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/hints", response_model=Hint, status_code=201)
def create_hint(project_id: str, body: CreateHintRequest):
    with get_conn() as conn:
        check_project_hint_writable(conn, project_id)
        now = utcnow()
        hid = next_hint_id(conn, project_id)
        conn.execute(
            "INSERT INTO hints (id, project_id, content, creator, created_at) VALUES (?, ?, ?, ?, ?)",
            (hid, project_id, body.content, body.creator, now),
        )
        return Hint(id=hid, content=body.content, creator=body.creator, created_at=now)


# ---------------------------------------------------------------------------
# Intents — create / heartbeat / release / conclude
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/intents", response_model=Intent, status_code=201)
def create_intent(project_id: str, body: CreateIntentRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        validate_facts_exist(conn, project_id, body.from_)
        validate_goal_not_in_sources(body.from_)
        validate_intent_creator_worker(body.creator, body.worker)

        now = utcnow()
        iid = next_intent_id(conn, project_id)
        claimed = body.worker is not None
        conn.execute(
            "INSERT INTO intents (id, project_id, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, NULL)",
            (iid, project_id, body.description, body.creator, body.worker, now if claimed else None, now),
        )
        for fid in body.from_:
            conn.execute(
                "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
                (iid, project_id, fid),
            )

        return Intent(
            id=iid,
            **{"from": body.from_},
            to=None,
            description=body.description,
            creator=body.creator,
            worker=body.worker,
            last_heartbeat_at=now if claimed else None,
            created_at=now,
            concluded_at=None,
        )


@router.post("/projects/{project_id}/intents/{intent_id}/heartbeat", response_model=Intent)
def heartbeat_intent(project_id: str, intent_id: str, body: HeartbeatRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        get_claimable_open_intent_or_404(conn, project_id, intent_id, body.worker)

        now = utcnow()
        conn.execute(
            "UPDATE intents SET worker = ?, last_heartbeat_at = ? WHERE id = ? AND project_id = ?",
            (body.worker, now, intent_id, project_id),
        )

        updated = conn.execute(
            "SELECT * FROM intents WHERE id = ? AND project_id = ?",
            (intent_id, project_id),
        ).fetchone()
        return intent_to_model(conn, updated, project_id)


@router.post("/projects/{project_id}/intents/{intent_id}/release", response_model=Intent)
def release_intent(project_id: str, intent_id: str, body: HeartbeatRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        row = get_releasable_open_intent_or_404(conn, project_id, intent_id, body.worker)

        if row["worker"] == body.worker:
            conn.execute(
                "UPDATE intents SET worker = NULL WHERE id = ? AND project_id = ?",
                (intent_id, project_id),
            )
            row = conn.execute(
                "SELECT * FROM intents WHERE id = ? AND project_id = ?",
                (intent_id, project_id),
            ).fetchone()

        return intent_to_model(conn, row, project_id)


@router.post("/projects/{project_id}/intents/{intent_id}/conclude", response_model=ConcludeResponse)
def conclude_intent(project_id: str, intent_id: str, body: ConcludeRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        get_claimable_open_intent_or_404(conn, project_id, intent_id, body.worker)

        now = utcnow()
        fid = next_fact_id(conn, project_id)

        conn.execute(
            "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
            (fid, project_id, body.description),
        )
        conn.execute(
            "UPDATE intents SET to_fact_id = ?, worker = ?, last_heartbeat_at = ?, concluded_at = ? WHERE id = ? AND project_id = ?",
            (fid, body.worker, now, now, intent_id, project_id),
        )

        updated = conn.execute(
            "SELECT * FROM intents WHERE id = ? AND project_id = ?",
            (intent_id, project_id),
        ).fetchone()

        return ConcludeResponse(
            fact=Fact(id=fid, description=body.description),
            intent=intent_to_model(conn, updated, project_id),
        )


# ---------------------------------------------------------------------------
# Complete / Reopen
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/complete", response_model=Intent)
def complete_project(project_id: str, body: CompleteRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        expire_reason_leases(conn, project_id)
        validate_facts_exist(conn, project_id, body.from_)
        validate_goal_not_in_sources(body.from_)

        now = utcnow()
        iid = next_intent_id(conn, project_id)

        conn.execute(
            "INSERT INTO intents (id, project_id, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at) VALUES (?, ?, 'goal', ?, ?, ?, ?, ?, ?)",
            (iid, project_id, body.description, body.worker, body.worker, now, now, now),
        )
        for fid in body.from_:
            conn.execute(
                "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
                (iid, project_id, fid),
            )
        conn.execute(
            """
            UPDATE projects
            SET status = 'completed',
                reason_worker = NULL,
                reason_trigger = NULL,
                reason_started_at = NULL,
                reason_last_heartbeat_at = NULL
            WHERE id = ?
            """,
            (project_id,),
        )

        return Intent(
            id=iid,
            **{"from": body.from_},
            to="goal",
            description=body.description,
            creator=body.worker,
            worker=body.worker,
            last_heartbeat_at=now,
            created_at=now,
            concluded_at=now,
        )


@router.post("/projects/{project_id}/reopen", response_model=ReopenResponse)
def reopen_project(project_id: str, body: ReopenRequest):
    with get_conn() as conn:
        expire_reason_leases(conn, project_id)
        check_project_completed(conn, project_id)
        completion = get_completion_intent_or_409(conn, project_id)

        source_rows = conn.execute(
            "SELECT fact_id FROM intent_sources WHERE intent_id = ? AND project_id = ? ORDER BY rowid",
            (completion["id"], project_id),
        ).fetchall()
        source_ids = [row["fact_id"] for row in source_rows]
        if not source_ids:
            source_ids = ["origin"]

        now = utcnow()
        fact_id = next_fact_id(conn, project_id)
        intent_id = next_intent_id(conn, project_id)
        description = body.description
        creator = body.creator

        conn.execute(
            "DELETE FROM intents WHERE id = ? AND project_id = ?",
            (completion["id"], project_id),
        )
        conn.execute(
            "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
            (fact_id, project_id, description),
        )
        conn.execute(
            "INSERT INTO intents (id, project_id, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (intent_id, project_id, fact_id, "external_feedback", creator, creator, now, now, now),
        )
        for source_id in source_ids:
            conn.execute(
                "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
                (intent_id, project_id, source_id),
            )
        clear_project_reason(conn, project_id)
        conn.execute(
            "UPDATE projects SET status = 'active' WHERE id = ?",
            (project_id,),
        )

        updated_project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        updated_intent = conn.execute(
            "SELECT * FROM intents WHERE id = ? AND project_id = ?",
            (intent_id, project_id),
        ).fetchone()
        assert updated_project is not None
        assert updated_intent is not None
        return ReopenResponse(
            project=project_meta_from_row(updated_project),
            fact=Fact(id=fact_id, description=description),
            intent=intent_to_model(conn, updated_intent, project_id),
        )


# ---------------------------------------------------------------------------
# Session Logs
# ---------------------------------------------------------------------------

from pydantic import BaseModel


class SessionLogEntry(BaseModel):
    id: str
    project_id: str
    intent_id: str | None = None
    session_id: str
    phase: str
    worker: str
    prompt_preview: str = ""
    status: str = "success"
    created_at: str


@router.get("/projects/{project_id}/session-logs", response_model=list[SessionLogEntry])
def get_session_logs(project_id: str):
    """List all worker session logs for a project."""
    with get_conn() as conn:
        rows = list_session_logs(conn, project_id)
        return [SessionLogEntry(**r) for r in rows]


@router.get("/projects/{project_id}/intents/{intent_id}/session-logs", response_model=list[SessionLogEntry])
def get_intent_session_logs(project_id: str, intent_id: str):
    """List session logs for a specific intent."""
    with get_conn() as conn:
        rows = list_session_logs_by_intent(conn, project_id, intent_id)
        return [SessionLogEntry(**r) for r in rows]


@router.get("/projects/{project_id}/facts/{fact_id}/session-logs", response_model=list[SessionLogEntry])
def get_fact_session_logs(project_id: str, fact_id: str):
    """List session logs associated with a specific fact."""
    with get_conn() as conn:
        rows = list_session_logs_by_fact(conn, project_id, fact_id)
        return [SessionLogEntry(**r) for r in rows]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _format_export_timestamp(value: str | None) -> str | None:
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


@router.get("/projects/{project_id}/export")
def export_project(project_id: str, format: str = "yaml"):
    if format not in ("yaml", "timeline"):
        raise HTTPException(400, "Supported formats: yaml, timeline")

    with get_conn() as conn:
        expire_workers(conn, project_id)
        expire_reason_leases(conn, project_id)
        proj = get_project_or_404(conn, project_id)

        facts = conn.execute(
            "SELECT id, description FROM facts WHERE project_id = ?", (project_id,)
        ).fetchall()
        hints = conn.execute(
            "SELECT content, creator, created_at FROM hints WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        intents = conn.execute(
            "SELECT * FROM intents WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()

        sources_by_intent = {}
        for i in intents:
            rows = conn.execute(
                "SELECT fact_id FROM intent_sources WHERE intent_id = ? AND project_id = ? ORDER BY rowid",
                (i["id"], project_id),
            ).fetchall()
            sources_by_intent[i["id"]] = [r["fact_id"] for r in rows]

        if format == "timeline":
            text = _export_timeline(proj, facts, hints, intents, sources_by_intent)
        else:
            text = _export_yaml(proj, facts, hints, intents, sources_by_intent)

        return Response(content=text, media_type="text/plain")


def _export_yaml(
    proj: dict, facts: list, hints: list, intents: list, sources_by_intent: dict
) -> str:
    origin_desc = ""
    goal_desc = ""
    for f in facts:
        if f["id"] == "origin":
            origin_desc = f["description"]
        elif f["id"] == "goal":
            goal_desc = f["description"]

    data: dict = {
        "project": {
            "title": proj["title"],
            "origin": origin_desc,
            "goal": goal_desc,
        }
    }

    if hints:
        data["hints"] = [
            {
                "content": h["content"],
                "creator": h["creator"],
                "created_at": _format_export_timestamp(h["created_at"]),
            }
            for h in hints
        ]

    data["facts"] = [{"id": f["id"], "description": f["description"]} for f in facts]

    intent_list = []
    for i in intents:
        entry: dict = {
            "from": sources_by_intent.get(i["id"], []),
            "to": i["to_fact_id"],
            "description": i["description"],
            "creator": i["creator"],
            "worker": i["worker"],
            "created_at": _format_export_timestamp(i["created_at"]),
            "concluded_at": _format_export_timestamp(i["concluded_at"]),
        }
        intent_list.append(entry)

    if intent_list:
        data["intents"] = intent_list

    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _export_timeline(
    proj: dict, facts: list, hints: list, intents: list, sources_by_intent: dict
) -> str:
    facts_by_id = {f["id"]: f["description"] for f in facts}

    events: list[tuple[str, int, str]] = []
    order = 0

    origin_desc = facts_by_id.get("origin", "")
    goal_desc = facts_by_id.get("goal", "")
    ts = _format_export_timestamp(proj["created_at"]) or ""
    block = f"[{ts}] PROJECT CREATED\n  origin: {origin_desc}\n  goal: {goal_desc}"
    events.append((proj["created_at"] or "", order, block))
    order += 1

    for h in hints:
        ts = _format_export_timestamp(h["created_at"]) or ""
        block = f"[{ts}] HINT by {h['creator']}\n  {h['content']}"
        events.append((h["created_at"] or "", order, block))
        order += 1

    for i in intents:
        src = sources_by_intent.get(i["id"], [])
        from_str = ", ".join(src)

        ts = _format_export_timestamp(i["created_at"]) or ""
        meta = f"  from: {from_str}"
        if i["worker"] and not i["concluded_at"]:
            meta += f"\n  worker: {i['worker']} (in progress)"
        block = f"[{ts}] INTENT DECLARED {i['id']} by {i['creator']}\n{meta}\n  {i['description']}"
        events.append((i["created_at"] or "", order, block))
        order += 1

        if not i["concluded_at"] or not i["to_fact_id"]:
            continue

        ts = _format_export_timestamp(i["concluded_at"]) or ""
        actor = i["worker"] or i["creator"]

        if i["to_fact_id"] == "goal":
            block = f"[{ts}] PROJECT COMPLETED by {actor}\n  via: {i['id']} from {from_str}"
        else:
            fact_desc = facts_by_id.get(i["to_fact_id"], "")
            block = f"[{ts}] INTENT CONCLUDED {i['id']} by {actor}\n  from: {from_str}\n  produced: {i['to_fact_id']}\n  {fact_desc}"

        events.append((i["concluded_at"] or "", order, block))
        order += 1

    events.sort(key=lambda e: (e[0], e[1]))
    return "\n\n".join(e[2] for e in events) + "\n"


# ---------------------------------------------------------------------------
# Dispatch (Flocks-specific: trigger scheduling for a project)
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/dispatch", status_code=202)
def dispatch_project(project_id: str):
    with get_conn() as conn:
        get_project_or_404(conn, project_id)
    # auto-start dispatcher if not running
    thread = _dispatcher_state["thread"]
    if thread is None or not thread.is_alive():
        stop_event = threading.Event()
        config_path = _get_dispatcher_config_path()
        thread = threading.Thread(
            target=_run_dispatcher,
            args=(config_path, stop_event),
            daemon=True,
        )
        _dispatcher_state["thread"] = thread
        _dispatcher_state["stop_event"] = stop_event
        thread.start()
    return {"status": "dispatched", "project_id": project_id}


@router.get("/dispatcher/status")
def dispatcher_status():
    thread = _dispatcher_state["thread"]
    is_running = thread is not None and thread.is_alive()
    return {
        "running": is_running,
        "project_id": None,
        "error": _dispatcher_state.get("error"),
    }


@router.post("/dispatcher/start", status_code=202)
def dispatcher_start():
    thread = _dispatcher_state["thread"]
    if thread is not None and thread.is_alive():
        raise HTTPException(409, "Dispatcher is already running")
    stop_event = threading.Event()
    config_path = _get_dispatcher_config_path()
    thread = threading.Thread(
        target=_run_dispatcher,
        args=(config_path, stop_event),
        daemon=True,
    )
    _dispatcher_state["thread"] = thread
    _dispatcher_state["stop_event"] = stop_event
    thread.start()
    return {"status": "started"}


@router.post("/dispatcher/stop", status_code=200)
def dispatcher_stop():
    stop_event = _dispatcher_state.get("stop_event")
    thread = _dispatcher_state.get("thread")
    if thread is None or not thread.is_alive():
        # already stopped — clean up and return success
        _dispatcher_state["thread"] = None
        _dispatcher_state["stop_event"] = None
        return {"status": "stopped"}
    stop_event.set()
    thread.join(timeout=15)
    _dispatcher_state["thread"] = None
    _dispatcher_state["stop_event"] = None
    return {"status": "stopped"}