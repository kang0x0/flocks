"""Cairn protocol client.

Provides a CairnClient abstraction that wraps storage operations directly,
matching the original Cairn architecture where the dispatcher talks
to the server via a client interface.

In Flocks, the dispatcher communicates with the server through direct
storage calls, not HTTP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import yaml
from fastapi import HTTPException

from flocks.cairn.models import (
    Fact,
    Hint,
    Intent,
    ProjectDetail,
    ProjectMeta,
    ProjectReason,
    ProjectSummary,
    Settings,
)
from flocks.cairn.storage import (
    build_intents,
    check_project_active,
    clear_project_reason,
    create_session_log,
    expire_reason_leases,
    expire_workers,
    get_claimable_open_intent_or_404,
    get_conn,
    get_project_or_404,
    get_releasable_open_intent_or_404,
    get_settings as storage_get_settings,
    intent_to_model,
    link_session_facts,
    next_fact_id,
    next_intent_id,
    project_meta_from_row,
    project_reason_from_row,
    update_session_log_status,
    utcnow,
    validate_facts_exist,
    validate_goal_not_in_sources,
    validate_intent_creator_worker,
)

LOG = logging.getLogger(__name__)


class ProtocolError(RuntimeError):
    def __init__(self, message: str, status_code: int, response_text: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


@dataclass(slots=True)
class ApiResult:
    status_code: int
    data: Any | None = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class CairnClient:
    """Client for Cairn storage operations.

    Wraps module-level storage functions from flocks.cairn.storage directly.
    Each method opens its own database connection via get_conn().
    """

    def close(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def list_projects(self) -> list[ProjectSummary]:
        with get_conn() as conn:
            expire_workers(conn)
            expire_reason_leases(conn)
            rows = conn.execute(
                """
                SELECT p.*,
                    (SELECT COUNT(*) FROM facts WHERE project_id = p.id) AS fact_count,
                    (SELECT COUNT(*) FROM intents WHERE project_id = p.id) AS intent_count,
                    (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NOT NULL) AS working_intent_count,
                    (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NULL) AS unclaimed_intent_count,
                    (SELECT COUNT(*) FROM hints WHERE project_id = p.id) AS hint_count
                FROM projects p
                ORDER BY p.created_at
                """
            ).fetchall()
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

    def get_project(self, project_id: str) -> ProjectDetail:
        with get_conn() as conn:
            expire_workers(conn, project_id)
            expire_reason_leases(conn, project_id)
            row = get_project_or_404(conn, project_id)
            facts = conn.execute(
                "SELECT id, description FROM facts WHERE project_id = ?", (project_id,)
            ).fetchall()
            hints = conn.execute(
                "SELECT id, content, creator, created_at FROM hints WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
            return ProjectDetail(
                project=project_meta_from_row(row),
                facts=[Fact(id=f["id"], description=f["description"]) for f in facts],
                intents=build_intents(conn, project_id),
                hints=[
                    Hint(id=h["id"], content=h["content"], creator=h["creator"], created_at=h["created_at"])
                    for h in hints
                ],
            )

    def get_settings(self) -> Settings:
        with get_conn() as conn:
            data = storage_get_settings(conn)
            return Settings(**data)

    def export_project(self, project_id: str) -> str:
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

    # ------------------------------------------------------------------
    # Heartbeats
    # ------------------------------------------------------------------

    def heartbeat(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        try:
            with get_conn() as conn:
                check_project_active(conn, project_id)
                get_claimable_open_intent_or_404(conn, project_id, intent_id, worker)
                now = utcnow()
                conn.execute(
                    "UPDATE intents SET worker = ?, last_heartbeat_at = ? WHERE id = ? AND project_id = ?",
                    (worker, now, intent_id, project_id),
                )
                updated = conn.execute(
                    "SELECT * FROM intents WHERE id = ? AND project_id = ?",
                    (intent_id, project_id),
                ).fetchone()
                return ApiResult(status_code=200, data=intent_to_model(conn, updated, project_id))
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("heartbeat failed project=%s intent=%s error=%s", project_id, intent_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    # ------------------------------------------------------------------
    # Reason lease
    # ------------------------------------------------------------------

    def claim_reason(self, project_id: str, worker: str, trigger: str) -> ApiResult:
        try:
            with get_conn() as conn:
                check_project_active(conn, project_id)
                expire_reason_leases(conn, project_id)
                row = get_project_or_404(conn, project_id)
                current_worker = row["reason_worker"]
                if current_worker is not None and current_worker != worker:
                    return ApiResult(status_code=409, text=f"Project reason is currently claimed by {current_worker}")
                if current_worker == worker:
                    return ApiResult(status_code=200, data=project_meta_from_row(row))

                now = utcnow()
                conn.execute(
                    """
                    UPDATE projects
                    SET reason_worker = ?, reason_trigger = ?, reason_started_at = ?, reason_last_heartbeat_at = ?
                    WHERE id = ?
                    """,
                    (worker, trigger, now, now, project_id),
                )
                updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
                return ApiResult(status_code=200, data=project_meta_from_row(updated))
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("claim_reason failed project=%s error=%s", project_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    def reason_heartbeat(self, project_id: str, worker: str) -> ApiResult:
        try:
            with get_conn() as conn:
                check_project_active(conn, project_id)
                expire_reason_leases(conn, project_id)
                row = get_project_or_404(conn, project_id)
                current_worker = row["reason_worker"]
                if current_worker is None:
                    return ApiResult(status_code=409, text="Project reason is not currently claimed")
                if current_worker != worker:
                    return ApiResult(status_code=409, text=f"Project reason is currently claimed by {current_worker}")

                now = utcnow()
                conn.execute(
                    "UPDATE projects SET reason_last_heartbeat_at = ? WHERE id = ?",
                    (now, project_id),
                )
                updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
                return ApiResult(status_code=200, data=project_meta_from_row(updated))
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("reason_heartbeat failed project=%s error=%s", project_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    def release_reason(self, project_id: str, worker: str) -> ApiResult:
        try:
            with get_conn() as conn:
                check_project_active(conn, project_id)
                expire_reason_leases(conn, project_id)
                row = get_project_or_404(conn, project_id)
                current_worker = row["reason_worker"]
                if current_worker is None:
                    return ApiResult(status_code=200, data=project_meta_from_row(row))
                if current_worker != worker:
                    return ApiResult(status_code=409, text=f"Project reason is currently claimed by {current_worker}")

                clear_project_reason(conn, project_id)
                updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
                return ApiResult(status_code=200, data=project_meta_from_row(updated))
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("release_reason failed project=%s error=%s", project_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    # ------------------------------------------------------------------
    # Intents
    # ------------------------------------------------------------------

    def release(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        try:
            with get_conn() as conn:
                check_project_active(conn, project_id)
                row = get_releasable_open_intent_or_404(conn, project_id, intent_id, worker)

                if row["worker"] == worker:
                    conn.execute(
                        "UPDATE intents SET worker = NULL WHERE id = ? AND project_id = ?",
                        (intent_id, project_id),
                    )
                    row = conn.execute(
                        "SELECT * FROM intents WHERE id = ? AND project_id = ?",
                        (intent_id, project_id),
                    ).fetchone()

                return ApiResult(status_code=200, data=intent_to_model(conn, row, project_id))
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("release failed project=%s intent=%s error=%s", project_id, intent_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    def conclude(self, project_id: str, intent_id: str, worker: str, description: str) -> ApiResult:
        try:
            with get_conn() as conn:
                check_project_active(conn, project_id)
                get_claimable_open_intent_or_404(conn, project_id, intent_id, worker)

                now = utcnow()
                fid = next_fact_id(conn, project_id)

                conn.execute(
                    "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
                    (fid, project_id, description),
                )
                conn.execute(
                    "UPDATE intents SET to_fact_id = ?, worker = ?, last_heartbeat_at = ?, concluded_at = ? WHERE id = ? AND project_id = ?",
                    (fid, worker, now, now, intent_id, project_id),
                )

                updated = conn.execute(
                    "SELECT * FROM intents WHERE id = ? AND project_id = ?",
                    (intent_id, project_id),
                ).fetchone()

                return ApiResult(
                    status_code=200,
                    data={
                        "fact": Fact(id=fid, description=description),
                        "intent": intent_to_model(conn, updated, project_id),
                    },
                )
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("conclude failed project=%s intent=%s error=%s", project_id, intent_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    def complete(self, project_id: str, from_ids: list[str], description: str, worker: str) -> ApiResult:
        if not from_ids:
            LOG.warning("complete called with empty from_ids project=%s worker=%s", project_id, worker)
            return ApiResult(status_code=0, text="from_ids must not be empty")
        try:
            with get_conn() as conn:
                check_project_active(conn, project_id)
                expire_reason_leases(conn, project_id)
                validate_facts_exist(conn, project_id, from_ids)
                validate_goal_not_in_sources(from_ids)

                now = utcnow()
                iid = next_intent_id(conn, project_id)

                conn.execute(
                    "INSERT INTO intents (id, project_id, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at) VALUES (?, ?, 'goal', ?, ?, ?, ?, ?, ?)",
                    (iid, project_id, description, worker, worker, now, now, now),
                )
                for fid in from_ids:
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

                return ApiResult(
                    status_code=200,
                    data=Intent(
                        id=iid,
                        from_=from_ids,
                        to="goal",
                        description=description,
                        creator=worker,
                        worker=worker,
                        last_heartbeat_at=now,
                        created_at=now,
                        concluded_at=now,
                    ),
                )
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("complete failed project=%s error=%s", project_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    def create_intent(self, project_id: str, from_ids: list[str], description: str, creator: str) -> ApiResult:
        try:
            with get_conn() as conn:
                check_project_active(conn, project_id)
                validate_facts_exist(conn, project_id, from_ids)
                validate_goal_not_in_sources(from_ids)
                validate_intent_creator_worker(creator, None)

                now = utcnow()
                iid = next_intent_id(conn, project_id)

                conn.execute(
                    "INSERT INTO intents (id, project_id, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at) VALUES (?, ?, NULL, ?, ?, NULL, NULL, ?, NULL)",
                    (iid, project_id, description, creator, now),
                )
                for fid in from_ids:
                    conn.execute(
                        "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
                        (iid, project_id, fid),
                    )

                return ApiResult(
                    status_code=200,
                    data=Intent(
                        id=iid,
                        from_=from_ids,
                        to=None,
                        description=description,
                        creator=creator,
                        worker=None,
                        last_heartbeat_at=None,
                        created_at=now,
                        concluded_at=None,
                    ),
                )
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("create_intent failed project=%s error=%s", project_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    # ------------------------------------------------------------------
    # Worker Session Logs
    # ------------------------------------------------------------------

    def create_session_log(
        self,
        project_id: str,
        session_id: str,
        phase: str,
        worker: str,
        *,
        intent_id: str | None = None,
        prompt_preview: str = "",
        status: str = "success",
    ) -> ApiResult:
        try:
            with get_conn() as conn:
                log_id = create_session_log(conn, project_id, session_id, phase, worker,
                                             intent_id=intent_id, prompt_preview=prompt_preview, status=status)
                return ApiResult(status_code=201, data={"id": log_id})
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("create_session_log failed project=%s error=%s", project_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    def update_session_log(self, project_id: str, log_id: str, status: str) -> ApiResult:
        try:
            with get_conn() as conn:
                update_session_log_status(conn, log_id, status)
                return ApiResult(status_code=200, data={"id": log_id, "status": status})
        except HTTPException as exc:
            return ApiResult(status_code=exc.status_code, text=exc.detail)
        except Exception as exc:
            LOG.warning("update_session_log failed project=%s log_id=%s error=%s", project_id, log_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    def link_session_facts(
        self,
        project_id: str,
        log_id: str,
        fact_ids: list[str],
    ) -> ApiResult:
        try:
            with get_conn() as conn:
                link_session_facts(conn, log_id, project_id, fact_ids)
                return ApiResult(status_code=200, data={"linked": len(fact_ids)})
        except Exception as exc:
            LOG.warning("link_session_facts failed project=%s error=%s", project_id, exc)
            return ApiResult(status_code=0, text=str(exc))

    def list_session_ids_for_project(self, project_id: str) -> ApiResult:
        try:
            from flocks.cairn.storage import list_session_ids_for_project as _list_sids
            with get_conn() as conn:
                ids = _list_sids(conn, project_id)
                return ApiResult(status_code=200, data=ids)
        except Exception as exc:
            LOG.warning("list_session_ids_for_project failed project=%s error=%s", project_id, exc)
            return ApiResult(status_code=0, text=str(exc))


def _format_export_timestamp(value: str | None) -> str | None:
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")