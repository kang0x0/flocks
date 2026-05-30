"""
Cairn protocol API routes.

Implements the Cairn collaboration protocol as FastAPI routes.
All endpoints follow the specification in docs/specs/server-protocol.md.

Key design decisions:
- Reuses Flocks authentication via require_user decorator
- Returns camelCase JSON for frontend compatibility
- Validates all inputs with Pydantic models
- Logs all state changes for audit trail
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from flocks.cairn.models import (
    ClaimReasonRequest,
    CompleteProjectRequest,
    ConcludeIntentRequest,
    CreateHintRequest,
    CreateIntentRequest,
    CreateProjectRequest,
    HeartbeatRequest,
    ProjectDetail,
    ProjectSummary,
    ReopenProjectRequest,
    UpdateProjectStatusRequest,
    UpdateProjectTitleRequest,
)
from flocks.cairn.storage import get_storage
from flocks.server.auth import require_user
from flocks.utils.log import Log

log = Log.create(service="cairn.protocol")

router = APIRouter(prefix="/api/cairn", tags=["cairn"])


# =============================================================================
# Settings (global configuration)
# =============================================================================

class Settings(BaseModel):
    intent_timeout: int = 300  # 5 minutes
    reason_timeout: int = 300  # 5 minutes


@router.get("/settings")
async def get_settings() -> Settings:
    """Get global Cairn settings."""
    return Settings()


@router.put("/settings")
async def update_settings(settings: Settings) -> Settings:
    """Update global Cairn settings."""
    # For now, just echo back (could be persisted to config)
    log.info("cairn.settings.updated", {"intent_timeout": settings.intent_timeout, "reason_timeout": settings.reason_timeout})
    return settings


# =============================================================================
# Projects
# =============================================================================

@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects():
    """List all projects with summary statistics."""
    storage = get_storage()
    await storage.initialize()
    
    projects = await storage.list_projects()
    return projects


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_project(request: CreateProjectRequest):
    """Create a new Cairn project."""
    storage = get_storage()
    await storage.initialize()
    
    try:
        project = await storage.create_project(
            title=request.title,
            origin=request.origin,
            goal=request.goal,
            hints=request.hints,
        )
        
        log.info("cairn.project.created_via_api", {
            "id": project.id,
            "title": project.title,
        })
        
        return {
            "id": project.id,
            "title": project.title,
            "status": project.status,
            "createdAt": project.created_at.isoformat(),
        }
    
    except Exception as e:
        log.error("cairn.project.create_failed", {"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """Get complete project data."""
    storage = get_storage()
    await storage.initialize()
    
    detail = await storage.get_project_detail(project_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {
        "project": {
            "id": detail.project.id,
            "title": detail.project.title,
            "status": detail.project.status,
            "createdAt": detail.project.created_at.isoformat(),
            "reason": {
                "worker": detail.project.reason.worker,
                "trigger": detail.project.reason.trigger,
                "startedAt": detail.project.reason.started_at.isoformat(),
                "lastHeartbeatAt": detail.project.reason.last_heartbeat_at.isoformat(),
            } if detail.project.reason else None,
        },
        "facts": [
            {
                "id": f.id,
                "description": f.description,
            }
            for f in detail.facts
        ],
        "intents": [
            {
                "id": i.id,
                "from": i.from_,
                "to": i.to,
                "description": i.description,
                "creator": i.creator,
                "worker": i.worker,
                "lastHeartbeatAt": i.last_heartbeat_at.isoformat() if i.last_heartbeat_at else None,
                "createdAt": i.created_at.isoformat(),
                "concludedAt": i.concluded_at.isoformat() if i.concluded_at else None,
            }
            for i in detail.intents
        ],
        "hints": [
            {
                "id": h.id,
                "content": h.content,
                "creator": h.creator,
                "createdAt": h.created_at.isoformat(),
            }
            for h in detail.hints
        ],
    }


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str):
    """Delete a project and all associated data."""
    storage = get_storage()
    await storage.initialize()
    
    deleted = await storage.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    
    log.info("cairn.project.deleted_via_api", {"id": project_id})


@router.put("/projects/{project_id}/title")
async def update_project_title(project_id: str, request: UpdateProjectTitleRequest):
    """Update project title."""
    storage = get_storage()
    await storage.initialize()
    
    project = await storage.update_project_title(project_id, request.title)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "createdAt": project.created_at.isoformat(),
        "reason": None,
    }


@router.put("/projects/{project_id}/status")
async def update_project_status(project_id: str, request: UpdateProjectStatusRequest):
    """Update project status (active <-> stopped only)."""
    storage = get_storage()
    await storage.initialize()
    
    try:
        project = await storage.update_project_status(project_id, request.status)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        log.info("cairn.project.status_updated", {
            "id": project_id,
            "status": request.status,
        })
        
        return {
            "id": project.id,
            "title": project.title,
            "status": project.status,
            "createdAt": project.created_at.isoformat(),
            "reason": None,
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# Reason lease operations
# =============================================================================

@router.post("/projects/{project_id}/reason/claim")
async def claim_reason(project_id: str, request: ClaimReasonRequest):
    """Claim project-level reason lease."""
    storage = get_storage()
    await storage.initialize()
    
    project = await storage.claim_reason(project_id, request.worker, request.trigger)
    if not project:
        # Check if project exists
        existing = await storage.get_project(project_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Check if already claimed by another worker
        if existing.reason and existing.reason.worker != request.worker:
            raise HTTPException(status_code=409, detail="Reason lease already claimed by another worker")
        
        raise HTTPException(status_code=403, detail="Project is not active")
    
    return {
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "createdAt": project.created_at.isoformat(),
        "reason": {
            "worker": project.reason.worker,
            "trigger": project.reason.trigger,
            "startedAt": project.reason.started_at.isoformat(),
            "lastHeartbeatAt": project.reason.last_heartbeat_at.isoformat(),
        } if project.reason else None,
    }


@router.post("/projects/{project_id}/reason/heartbeat")
async def heartbeat_reason(project_id: str, request: HeartbeatRequest):
    """Heartbeat reason lease."""
    storage = get_storage()
    await storage.initialize()
    
    project = await storage.heartbeat_reason(project_id, request.worker)
    if not project:
        existing = await storage.get_project(project_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Project not found")
        
        raise HTTPException(status_code=409, detail="Reason lease not claimed by this worker")
    
    return {
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "createdAt": project.created_at.isoformat(),
        "reason": {
            "worker": project.reason.worker,
            "trigger": project.reason.trigger,
            "startedAt": project.reason.started_at.isoformat(),
            "lastHeartbeatAt": project.reason.last_heartbeat_at.isoformat(),
        } if project.reason else None,
    }


@router.post("/projects/{project_id}/reason/release")
async def release_reason(project_id: str, request: HeartbeatRequest):
    """Release reason lease."""
    storage = get_storage()
    await storage.initialize()
    
    project = await storage.release_reason(project_id, request.worker)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "createdAt": project.created_at.isoformat(),
        "reason": None,
    }


# =============================================================================
# Hints
# =============================================================================

@router.post("/projects/{project_id}/hints", status_code=status.HTTP_201_CREATED)
async def create_hint(project_id: str, request: CreateHintRequest):
    """Add a hint to a project."""
    storage = get_storage()
    await storage.initialize()
    
    # Verify project exists
    project = await storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    hint = await storage.create_hint(project_id, request.content, request.creator)
    
    log.info("cairn.hint.created", {"id": hint.id, "project": project_id})
    
    return {
        "id": hint.id,
        "content": hint.content,
        "creator": hint.creator,
        "createdAt": hint.created_at.isoformat(),
    }


# =============================================================================
# Intents
# =============================================================================

@router.post("/projects/{project_id}/intents", status_code=status.HTTP_201_CREATED)
async def create_intent(project_id: str, request: CreateIntentRequest):
    """Create a new intent."""
    storage = get_storage()
    await storage.initialize()
    
    # Verify project is active
    project = await storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.status != "active":
        raise HTTPException(status_code=403, detail="Project is not active")
    
    try:
        intent = await storage.create_intent(
            project_id=project_id,
            from_facts=request.from_,
            description=request.description,
            creator=request.creator,
            worker=request.worker,
        )
        
        log.info("cairn.intent.created_via_api", {
            "id": intent.id,
            "project": project_id,
        })
        
        return {
            "id": intent.id,
            "from": intent.from_,
            "to": intent.to,
            "description": intent.description,
            "creator": intent.creator,
            "worker": intent.worker,
            "lastHeartbeatAt": intent.last_heartbeat_at.isoformat() if intent.last_heartbeat_at else None,
            "createdAt": intent.created_at.isoformat(),
            "concludedAt": None,
        }
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/projects/{project_id}/intents/{intent_id}/heartbeat")
async def heartbeat_intent(project_id: str, intent_id: str, request: HeartbeatRequest):
    """Heartbeat an intent (claim or renew)."""
    storage = get_storage()
    await storage.initialize()
    
    # Verify project is active
    project = await storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.status != "active":
        raise HTTPException(status_code=403, detail="Project is not active")
    
    intent = await storage.heartbeat_intent(project_id, intent_id, request.worker)
    if not intent:
        # Check if intent exists
        detail = await storage.get_project_detail(project_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Project not found")
        
        intent_exists = any(i.id == intent_id for i in detail.intents)
        if not intent_exists:
            raise HTTPException(status_code=404, detail="Intent not found")
        
        raise HTTPException(status_code=409, detail="Intent already claimed by another worker")
    
    return {
        "id": intent.id,
        "from": intent.from_,
        "to": intent.to,
        "description": intent.description,
        "creator": intent.creator,
        "worker": intent.worker,
        "lastHeartbeatAt": intent.last_heartbeat_at.isoformat() if intent.last_heartbeat_at else None,
        "createdAt": intent.created_at.isoformat(),
        "concludedAt": intent.concluded_at.isoformat() if intent.concluded_at else None,
    }


@router.post("/projects/{project_id}/intents/{intent_id}/release")
async def release_intent(project_id: str, intent_id: str, request: HeartbeatRequest):
    """Release an intent (make it unclaimed)."""
    storage = get_storage()
    await storage.initialize()
    
    # Verify project is active
    project = await storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.status != "active":
        raise HTTPException(status_code=403, detail="Project is not active")
    
    intent = await storage.release_intent(project_id, intent_id, request.worker)
    if not intent:
        detail = await storage.get_project_detail(project_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Project not found")
        
        intent_exists = any(i.id == intent_id for i in detail.intents)
        if not intent_exists:
            raise HTTPException(status_code=404, detail="Intent not found")
        
        raise HTTPException(status_code=409, detail="Intent not claimed by this worker")
    
    return {
        "id": intent.id,
        "from": intent.from_,
        "to": intent.to,
        "description": intent.description,
        "creator": intent.creator,
        "worker": intent.worker,
        "lastHeartbeatAt": intent.last_heartbeat_at.isoformat() if intent.last_heartbeat_at else None,
        "createdAt": intent.created_at.isoformat(),
        "concludedAt": intent.concluded_at.isoformat() if intent.concluded_at else None,
    }


@router.post("/projects/{project_id}/intents/{intent_id}/conclude")
async def conclude_intent(project_id: str, intent_id: str, request: ConcludeIntentRequest):
    """Conclude an intent with a new fact."""
    storage = get_storage()
    await storage.initialize()
    
    # Verify project is active
    project = await storage.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.status != "active":
        raise HTTPException(status_code=403, detail="Project is not active")
    
    result = await storage.conclude_intent(project_id, intent_id, request.worker, request.description)
    if not result:
        detail = await storage.get_project_detail(project_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Project not found")
        
        intent_exists = any(i.id == intent_id for i in detail.intents)
        if not intent_exists:
            raise HTTPException(status_code=404, detail="Intent not found")
        
        raise HTTPException(status_code=409, detail="Intent cannot be concluded by this worker")
    
    fact, intent = result
    
    log.info("cairn.intent.concluded_via_api", {
        "intent_id": intent_id,
        "fact_id": fact.id,
    })
    
    return {
        "fact": {
            "id": fact.id,
            "description": fact.description,
        },
        "intent": {
            "id": intent.id,
            "from": intent.from_,
            "to": intent.to,
            "description": intent.description,
            "creator": intent.creator,
            "worker": intent.worker,
            "lastHeartbeatAt": intent.last_heartbeat_at.isoformat() if intent.last_heartbeat_at else None,
            "createdAt": intent.created_at.isoformat(),
            "concludedAt": intent.concluded_at.isoformat() if intent.concluded_at else None,
        },
    }


# =============================================================================
# Project completion/reopening
# =============================================================================

@router.post("/projects/{project_id}/complete")
async def complete_project(project_id: str, request: CompleteProjectRequest):
    """Mark project as completed."""
    storage = get_storage()
    await storage.initialize()
    
    result = await storage.complete_project(
        project_id=project_id,
        from_facts=request.from_,
        description=request.description,
        worker=request.worker,
    )
    
    if not result:
        project = await storage.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if project.status != "active":
            raise HTTPException(status_code=403, detail="Project is not active")
        
        raise HTTPException(status_code=400, detail="Cannot complete project")
    
    project, intent = result
    
    log.info("cairn.project.completed_via_api", {"id": project_id})
    
    return {
        "project": {
            "id": project.id,
            "title": project.title,
            "status": project.status,
            "createdAt": project.created_at.isoformat(),
            "reason": None,
        },
        "intent": {
            "id": intent.id,
            "from": intent.from_,
            "to": intent.to,
            "description": intent.description,
            "creator": intent.creator,
            "worker": intent.worker,
            "lastHeartbeatAt": intent.last_heartbeat_at.isoformat() if intent.last_heartbeat_at else None,
            "createdAt": intent.created_at.isoformat(),
            "concludedAt": intent.concluded_at.isoformat() if intent.concluded_at else None,
        },
    }


@router.post("/projects/{project_id}/reopen")
async def reopen_project(project_id: str, request: ReopenProjectRequest):
    """Reopen a completed project."""
    storage = get_storage()
    await storage.initialize()
    
    result = await storage.reopen_project(project_id, request.description, request.creator)
    if not result:
        project = await storage.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        if project.status != "completed":
            raise HTTPException(status_code=400, detail="Project is not completed")
        
        raise HTTPException(status_code=400, detail="Cannot reopen project")
    
    project, fact, intent = result
    
    log.info("cairn.project.reopened_via_api", {"id": project_id})
    
    return {
        "project": {
            "id": project.id,
            "title": project.title,
            "status": project.status,
            "createdAt": project.created_at.isoformat(),
            "reason": None,
        },
        "fact": {
            "id": fact.id,
            "description": fact.description,
        },
        "intent": {
            "id": intent.id,
            "from": intent.from_,
            "to": intent.to,
            "description": intent.description,
            "creator": intent.creator,
            "worker": intent.worker,
            "lastHeartbeatAt": intent.last_heartbeat_at.isoformat() if intent.last_heartbeat_at else None,
            "createdAt": intent.created_at.isoformat(),
            "concludedAt": intent.concluded_at.isoformat() if intent.concluded_at else None,
        },
    }


# =============================================================================
# Export
# =============================================================================

@router.get("/projects/{project_id}/export")
async def export_project(project_id: str, format: str = "yaml"):
    """Export project in specified format."""
    storage = get_storage()
    await storage.initialize()
    
    if format == "yaml":
        yaml_content = await storage.export_yaml(project_id)
        if not yaml_content:
            raise HTTPException(status_code=404, detail="Project not found")
        
        from fastapi.responses import PlainTextResponse
        
        return PlainTextResponse(
            content=yaml_content,
            media_type="text/yaml",
            headers={"Content-Disposition": f"attachment; filename={project_id}.yaml"},
        )
    
    elif format == "timeline":
        # TODO: Implement timeline export
        raise HTTPException(status_code=501, detail="Timeline export not yet implemented")
    
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
