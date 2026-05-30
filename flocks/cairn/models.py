"""
Cairn data models.

Defines the core entities: Project, Fact, Intent, Hint, and ReasonLease.
These models map to the SQLite database schema and API contracts.

Design principles:
- Facts are immutable once created (append-only)
- Intents track exploration progress through worker/heartbeat/concluded_at
- Hints are external inputs that don't affect graph causality
- ReasonLease is project-level coordination state (not part of the graph)
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Fact(BaseModel):
    """A confirmed objective finding in the exploration graph."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = Field(..., description="Fact ID: 'origin', 'goal', or system-generated like 'f001'")
    project_id: str = Field(..., alias="projectID", description="Parent project ID")
    description: str = Field(..., min_length=1, description="Objective fact description")
    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")
    
    def is_special(self) -> bool:
        """Check if this is a special fact (origin or goal)."""
        return self.id in ("origin", "goal")


class Intent(BaseModel):
    """An exploration direction from one or more Facts."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = Field(..., description="Intent ID: 'i001', 'i002', etc.")
    project_id: str = Field(..., alias="projectID", description="Parent project ID")
    from_: List[str] = Field(..., alias="from", min_length=1, description="Source Fact IDs (hyperedge support)")
    to: Optional[str] = Field(None, alias="to", description="Conclusion Fact ID (null means not concluded)")
    description: str = Field(..., min_length=1, description="Intent description")
    creator: str = Field(..., min_length=1, description="Who declared this intent (immutable)")
    worker: Optional[str] = Field(None, description="Current worker handling this intent (null = unclaimed)")
    last_heartbeat_at: Optional[datetime] = Field(None, alias="lastHeartbeatAt", description="Last heartbeat time")
    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")
    concluded_at: Optional[datetime] = Field(None, alias="concludedAt", description="When this intent was concluded")
    
    @property
    def is_concluded(self) -> bool:
        """Check if this intent has been concluded."""
        return self.to is not None and self.concluded_at is not None
    
    @property
    def is_unclaimed(self) -> bool:
        """Check if this intent is unclaimed (no worker assigned)."""
        return self.worker is None and not self.is_concluded
    
    @property
    def is_active(self) -> bool:
        """Check if this intent is actively being worked on."""
        return self.worker is not None and not self.is_concluded


class Hint(BaseModel):
    """External strategy suggestion (not part of the causal graph)."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = Field(..., description="Hint ID: 'h001', 'h002', etc.")
    project_id: str = Field(..., alias="projectID", description="Parent project ID")
    content: str = Field(..., min_length=1, description="Hint content")
    creator: str = Field(..., min_length=1, description="Who created this hint")
    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")


class ReasonLease(BaseModel):
    """Project-level coordination state for reason tasks."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    worker: str = Field(..., min_length=1, description="Worker currently executing reason")
    trigger: str = Field(..., min_length=1, description="What triggered this reason task")
    started_at: datetime = Field(default_factory=datetime.utcnow, alias="startedAt")
    last_heartbeat_at: datetime = Field(default_factory=datetime.utcnow, alias="lastHeartbeatAt")


class Project(BaseModel):
    """A Cairn problem-solving project."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = Field(..., description="Project ID")
    title: str = Field(..., min_length=1, description="Project title")
    status: Literal["active", "stopped", "completed"] = Field(
        default="active",
        description="Project status"
    )
    origin_fact_id: str = Field(..., alias="originFactId", description="Origin fact ID (always 'origin')")
    goal_fact_id: str = Field(..., alias="goalFactId", description="Goal fact ID (always 'goal')")
    reason: Optional[ReasonLease] = Field(None, description="Current reason lease (null if none)")
    created_at: datetime = Field(default_factory=datetime.utcnow, alias="createdAt")
    updated_at: datetime = Field(default_factory=datetime.utcnow, alias="updatedAt")


class ProjectDetail(BaseModel):
    """Complete project data including facts, intents, and hints."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    project: Project
    facts: List[Fact]
    intents: List[Intent]
    hints: List[Hint]


class ProjectSummary(BaseModel):
    """Project summary for list view (without full graph data)."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = Field(..., alias="id")
    title: str = Field(..., alias="title")
    status: Literal["active", "stopped", "completed"] = Field(..., alias="status")
    created_at: datetime = Field(..., alias="createdAt")
    reason: Optional[ReasonLease] = Field(None, alias="reason")
    fact_count: int = Field(..., alias="factCount")
    intent_count: int = Field(..., alias="intentCount")
    working_intent_count: int = Field(..., alias="workingIntentCount")
    unclaimed_intent_count: int = Field(..., alias="unclaimedIntentCount")
    hint_count: int = Field(..., alias="hintCount")


# =============================================================================
# API Request/Response Models
# =============================================================================

class CreateProjectRequest(BaseModel):
    """Request to create a new Cairn project."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    title: str = Field(..., min_length=1, description="Project title")
    origin: str = Field(..., min_length=1, description="Starting point description")
    goal: str = Field(..., min_length=1, description="Goal description")
    hints: Optional[List[Dict[str, str]]] = Field(
        None,
        description="Initial hints: [{'content': '...', 'creator': '...'}]"
    )


class CreateIntentRequest(BaseModel):
    """Request to create a new intent."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    from_: List[str] = Field(..., alias="from", min_length=1, description="Source Fact IDs")
    description: str = Field(..., min_length=1, description="Intent description")
    creator: str = Field(..., min_length=1, description="Who is declaring this intent")
    worker: Optional[str] = Field(None, description="Worker to claim immediately (null or equal to creator)")


class HeartbeatRequest(BaseModel):
    """Request to heartbeat an intent or reason lease."""
    
    worker: str = Field(..., min_length=1, description="Worker identifier")


class ConcludeIntentRequest(BaseModel):
    """Request to conclude an intent with a new fact."""
    
    worker: str = Field(..., min_length=1, description="Worker producing the conclusion")
    description: str = Field(..., min_length=1, description="New fact description")


class CompleteProjectRequest(BaseModel):
    """Request to mark a project as completed."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    from_: List[str] = Field(..., alias="from", min_length=1, description="Facts that satisfy the goal")
    description: str = Field(..., min_length=1, description="Completion description")
    worker: str = Field(..., min_length=1, description="Worker declaring completion")


class CreateHintRequest(BaseModel):
    """Request to add a hint to a project."""
    
    content: str = Field(..., min_length=1, description="Hint content")
    creator: str = Field(..., min_length=1, description="Hint author")


class ClaimReasonRequest(BaseModel):
    """Request to claim project-level reason lease."""
    
    worker: str = Field(..., min_length=1, description="Worker claiming the lease")
    trigger: str = Field(..., min_length=1, description="What triggered this reason")


class UpdateProjectTitleRequest(BaseModel):
    """Request to update project title."""
    
    title: str = Field(..., min_length=1, description="New project title")


class UpdateProjectStatusRequest(BaseModel):
    """Request to update project status."""
    
    status: Literal["active", "stopped"] = Field(..., description="New status (cannot set to completed via this API)")


class ReopenProjectRequest(BaseModel):
    """Request to reopen a completed project."""
    
    description: str = Field(..., min_length=1, description="Feedback description (will be added as a new fact)")
    creator: str = Field(..., min_length=1, description="Who is providing the feedback")


# =============================================================================
# Export Format Models
# =============================================================================

class ExportYamlFact(BaseModel):
    """Fact representation in YAML export."""
    
    id: str
    description: str


class ExportYamlIntent(BaseModel):
    """Intent representation in YAML export."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    from_: List[str] = Field(..., alias="from")
    to: Optional[str] = Field(None, alias="to")
    description: str
    creator: str
    worker: Optional[str]
    created_at: str = Field(..., alias="created_at")
    concluded_at: Optional[str] = Field(None, alias="concluded_at")


class ExportYamlHint(BaseModel):
    """Hint representation in YAML export."""
    
    content: str
    creator: str
    created_at: str = Field(..., alias="created_at")


class ExportYamlProject(BaseModel):
    """Complete project export in YAML format."""
    
    model_config = ConfigDict(populate_by_name=True)
    
    project: Dict[str, Any]
    facts: List[ExportYamlFact]
    intents: List[ExportYamlIntent]
    hints: List[ExportYamlHint]
