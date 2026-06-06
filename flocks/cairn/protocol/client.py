"""Cairn protocol client.

Provides a CairnClient abstraction that wraps storage operations,
matching the original Cairn architecture where the dispatcher talks
to the server via a client interface.

This enables:
1. Direct storage access (current mode, everything in-process)
2. Future HTTP-based access (when dispatcher runs as separate process)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from flocks.cairn.models import (
    Fact,
    Hint,
    Intent,
    ProjectDetail,
    ProjectMeta,
    ProjectReason,
    ProjectSummary,
    Settings,
    WorkerSessionLog,
)
from flocks.cairn.storage import CairnStorage, get_storage

LOG = logging.getLogger(__name__)


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

    Currently wraps CairnStorage directly (in-process).
    The interface mirrors the original Cairn's HTTP client so that
    a future HTTP-backed implementation can be swapped in without
    changing the dispatcher code.
    """

    def __init__(self, storage: CairnStorage | None = None):
        self._storage = storage or get_storage()

    def close(self) -> None:
        self._storage.close()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_settings(self) -> Settings:
        data = self._storage.get_settings()
        return Settings(**data)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def list_projects(self) -> list[ProjectSummary]:
        rows = self._storage.list_projects()
        return [_dict_to_summary(r) for r in rows]

    def get_project(self, project_id: str) -> ProjectDetail:
        project_row = self._storage.get_project(project_id)
        if not project_row:
            raise ValueError(f"Project {project_id} not found")
        facts = self._storage.get_facts(project_id)
        intents = self._storage.get_intents(project_id)
        hints = self._storage.get_hints(project_id)
        return ProjectDetail(
            project=_dict_to_meta(project_row),
            facts=[Fact(id=f["id"], description=f["description"]) for f in facts],
            intents=[_dict_to_intent(i) for i in intents],
            hints=[Hint(id=h["id"], content=h["content"], creator=h["creator"], created_at=h["created_at"]) for h in hints],
        )

    def get_project_meta(self, project_id: str) -> ProjectMeta | None:
        row = self._storage.get_project(project_id)
        if not row:
            return None
        reason = _dict_to_reason(row)
        return ProjectMeta(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            created_at=row["created_at"],
            reason=reason,
        )

    def export_project(self, project_id: str) -> str:
        result = self._storage.export_yaml(project_id)
        if result is None:
            raise ValueError(f"Project {project_id} not found")
        return result

    # ------------------------------------------------------------------
    # Heartbeats
    # ------------------------------------------------------------------

    def heartbeat(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        try:
            result = self._storage.heartbeat_intent(project_id, intent_id, worker)
            if result is None:
                return ApiResult(status_code=403, text="intent not claimable or already concluded")
            return ApiResult(status_code=200, data=result)
        except Exception as exc:
            LOG.warning("heartbeat failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    # ------------------------------------------------------------------
    # Reason lease
    # ------------------------------------------------------------------

    def claim_reason(self, project_id: str, worker: str, trigger: str) -> ApiResult:
        try:
            result = self._storage.claim_reason(project_id, worker, trigger)
            if result is None:
                return ApiResult(status_code=403, text="reason not claimable")
            return ApiResult(status_code=200, data=result)
        except Exception as exc:
            LOG.warning("claim_reason failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def reason_heartbeat(self, project_id: str, worker: str) -> ApiResult:
        try:
            result = self._storage.heartbeat_reason(project_id, worker)
            if result is None:
                return ApiResult(status_code=403, text="reason lease not found")
            return ApiResult(status_code=200, data=result)
        except Exception as exc:
            LOG.warning("reason_heartbeat failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def release_reason(self, project_id: str, worker: str) -> ApiResult:
        try:
            result = self._storage.release_reason(project_id, worker)
            if result is None:
                return ApiResult(status_code=404)
            return ApiResult(status_code=200, data=result)
        except Exception as exc:
            LOG.warning("release_reason failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    # ------------------------------------------------------------------
    # Intents
    # ------------------------------------------------------------------

    def release(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        try:
            result = self._storage.release_intent(project_id, intent_id, worker)
            if result is None:
                return ApiResult(status_code=403, text="intent not releasable")
            return ApiResult(status_code=200, data=result)
        except Exception as exc:
            LOG.warning("release failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def conclude(self, project_id: str, intent_id: str, worker: str, description: str) -> ApiResult:
        try:
            result = self._storage.conclude_intent(project_id, intent_id, worker, description)
            if result is None:
                return ApiResult(status_code=403, text="intent not concludable")
            return ApiResult(status_code=200, data=result)
        except Exception as exc:
            LOG.warning("conclude failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def complete(self, project_id: str, from_ids: list[str], description: str, worker: str) -> ApiResult:
        try:
            result = self._storage.complete_project(project_id, from_ids, description, worker)
            if result is None:
                return ApiResult(status_code=403, text="project not completable")
            return ApiResult(status_code=200, data=result)
        except Exception as exc:
            LOG.warning("complete failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def create_intent(self, project_id: str, from_ids: list[str], description: str, creator: str) -> ApiResult:
        try:
            result = self._storage.create_intent(project_id, from_ids, description, creator, worker=None)
            return ApiResult(status_code=200, data=result)
        except Exception as exc:
            LOG.warning("create_intent failed: %s", exc)
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
            result = self._storage.create_session_log(
                project_id, session_id, phase, worker,
                intent_id=intent_id, prompt_preview=prompt_preview, status=status,
            )
            return ApiResult(status_code=201, data=result)
        except Exception as exc:
            LOG.warning("create_session_log failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def list_session_logs(self, project_id: str) -> ApiResult:
        try:
            rows = self._storage.list_session_logs(project_id)
            return ApiResult(status_code=200, data=[WorkerSessionLog(**r) for r in rows])
        except Exception as exc:
            LOG.warning("list_session_logs failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def list_session_logs_by_intent(self, project_id: str, intent_id: str) -> ApiResult:
        try:
            rows = self._storage.list_session_logs_by_intent(project_id, intent_id)
            return ApiResult(status_code=200, data=[WorkerSessionLog(**r) for r in rows])
        except Exception as exc:
            LOG.warning("list_session_logs_by_intent failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def list_session_logs_by_fact(self, project_id: str, fact_id: str) -> ApiResult:
        try:
            rows = self._storage.list_session_logs_by_fact(project_id, fact_id)
            return ApiResult(status_code=200, data=[WorkerSessionLog(**r) for r in rows])
        except Exception as exc:
            LOG.warning("list_session_logs_by_fact failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))

    def list_session_ids_for_project(self, project_id: str) -> ApiResult:
        try:
            ids = self._storage.list_session_ids_for_project(project_id)
            return ApiResult(status_code=200, data=ids)
        except Exception as exc:
            LOG.warning("list_session_ids_for_project failed: %s", exc)
            return ApiResult(status_code=0, text=str(exc))


# ------------------------------------------------------------------
# Conversion helpers
# ------------------------------------------------------------------

def _dict_to_meta(row: dict) -> ProjectMeta:
    reason = _dict_to_reason(row)
    return ProjectMeta(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        reason=reason,
    )


def _dict_to_reason(row: dict) -> ProjectReason | None:
    if row.get("reason_worker") is None:
        return None
    return ProjectReason(
        worker=row["reason_worker"],
        trigger=row["reason_trigger"] or "",
        started_at=row["reason_started_at"] or "",
        last_heartbeat_at=row["reason_last_heartbeat_at"] or "",
    )


def _dict_to_summary(row: dict) -> ProjectSummary:
    reason = _dict_to_reason(row)
    return ProjectSummary(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        reason=reason,
        fact_count=row["fact_count"],
        intent_count=row["intent_count"],
        working_intent_count=row["working_intent_count"],
        unclaimed_intent_count=row["unclaimed_intent_count"],
        hint_count=row["hint_count"],
    )


def _dict_to_intent(row: dict) -> Intent:
    return Intent(
        id=row["id"],
        from_=row.get("from", []),
        to=row.get("to_fact_id"),
        description=row["description"],
        creator=row["creator"],
        worker=row.get("worker"),
        last_heartbeat_at=row.get("last_heartbeat_at"),
        created_at=row["created_at"],
        concluded_at=row.get("concluded_at"),
    )


