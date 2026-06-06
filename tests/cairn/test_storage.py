"""
Tests for Cairn storage layer.

Validates CRUD operations, timeout handling, and data integrity.
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile

from flocks.cairn.models import Fact, Intent, Hint, Project
from flocks.cairn.storage import CairnStorage


@pytest.fixture
async def storage():
    """Create temporary storage for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cairn.db"
        storage = CairnStorage(db_path=db_path)
        await storage.initialize()
        yield storage


@pytest.mark.asyncio
async def test_create_project(storage):
    """Test project creation with origin and goal facts."""
    project = await storage.create_project(
        title="Test Project",
        origin="Starting point",
        goal="Target objective",
        hints=[{"content": "Initial hint", "creator": "test"}]
    )
    
    assert project.title == "Test Project"
    assert project.status == "active"
    assert project.origin_fact_id == "origin"
    assert project.goal_fact_id == "goal"
    
    # Verify facts were created
    facts = await storage.get_facts(project.id)
    assert len(facts) == 2
    assert any(f.id == "origin" for f in facts)
    assert any(f.id == "goal" for f in facts)


@pytest.mark.asyncio
async def test_list_projects(storage):
    """Test listing projects with summary statistics."""
    # Create multiple projects
    p1 = await storage.create_project("Project 1", "Origin 1", "Goal 1")
    p2 = await storage.create_project("Project 2", "Origin 2", "Goal 2")
    
    summaries = await storage.list_projects()
    assert len(summaries) == 2
    
    # Check summary fields
    summary = summaries[0]
    assert hasattr(summary, 'fact_count')
    assert hasattr(summary, 'intent_count')
    assert hasattr(summary, 'hint_count')


@pytest.mark.asyncio
async def test_create_and_get_intent(storage):
    """Test intent lifecycle."""
    project = await storage.create_project("Test", "Origin", "Goal")
    
    # Create intent
    intent = await storage.create_intent(
        project_id=project.id,
        from_facts=["origin"],
        description="Explore origin",
        creator="test-user"
    )
    
    assert intent.from_ == ["origin"]
    assert intent.to is None
    assert intent.worker is None
    
    # Get intents
    intents = await storage.get_intents(project.id)
    assert len(intents) == 1
    assert intents[0].id == intent.id


@pytest.mark.asyncio
async def test_heartbeat_intent(storage):
    """Test claiming and heartbeating intents."""
    project = await storage.create_project("Test", "Origin", "Goal")
    intent = await storage.create_intent(project.id, ["origin"], "Explore", "user")
    
    # Claim intent
    claimed = await storage.heartbeat_intent(project.id, intent.id, "worker-1")
    assert claimed is not None
    assert claimed.worker == "worker-1"
    assert claimed.last_heartbeat_at is not None
    
    # Heartbeat again
    renewed = await storage.heartbeat_intent(project.id, intent.id, "worker-1")
    assert renewed is not None
    assert renewed.worker == "worker-1"


@pytest.mark.asyncio
async def test_concurrent_intent_claim(storage):
    """Test that two workers cannot claim the same intent simultaneously."""
    project = await storage.create_project("Test", "Origin", "Goal")
    intent = await storage.create_intent(project.id, ["origin"], "Explore", "user")
    
    # First worker claims
    claimed1 = await storage.heartbeat_intent(project.id, intent.id, "worker-1")
    assert claimed1 is not None
    
    # Second worker tries to claim (should fail within timeout window)
    claimed2 = await storage.heartbeat_intent(project.id, intent.id, "worker-2")
    assert claimed2 is None  # Should be rejected


@pytest.mark.asyncio
async def test_conclude_intent(storage):
    """Test concluding an intent with a new fact."""
    project = await storage.create_project("Test", "Origin", "Goal")
    intent = await storage.create_intent(project.id, ["origin"], "Explore", "user")
    
    # Claim intent
    await storage.heartbeat_intent(project.id, intent.id, "worker-1")
    
    # Conclude with new fact
    result = await storage.conclude_intent(
        project_id=project.id,
        intent_id=intent.id,
        worker="worker-1",
        fact_description="New discovery"
    )
    
    assert result is not None
    fact, concluded_intent = result
    
    assert fact.description == "New discovery"
    assert concluded_intent.to == fact.id
    assert concluded_intent.concluded_at is not None
    
    # Verify fact was added to project
    facts = await storage.get_facts(project.id)
    assert len(facts) == 3  # origin, goal, new fact


@pytest.mark.asyncio
async def test_create_hint(storage):
    """Test hint creation."""
    project = await storage.create_project("Test", "Origin", "Goal")
    
    hint = await storage.create_hint(
        project_id=project.id,
        content="Strategic suggestion",
        creator="analyst"
    )
    
    assert hint.content == "Strategic suggestion"
    assert hint.creator == "analyst"
    
    hints = await storage.get_hints(project.id)
    assert len(hints) == 1


@pytest.mark.asyncio
async def test_reason_lease(storage):
    """Test project-level reason lease management."""
    project = await storage.create_project("Test", "Origin", "Goal")
    
    # Claim reason lease
    claimed = await storage.claim_reason(project.id, "reason-worker", "manual")
    assert claimed is not None
    assert claimed.reason is not None
    assert claimed.reason.worker == "reason-worker"
    
    # Heartbeat
    heartbeat = await storage.heartbeat_reason(project.id, "reason-worker")
    assert heartbeat is not None
    
    # Release
    released = await storage.release_reason(project.id, "reason-worker")
    assert released is not None
    assert released.reason is None


@pytest.mark.asyncio
async def test_complete_project(storage):
    """Test project completion."""
    project = await storage.create_project("Test", "Origin", "Goal")
    
    result = await storage.complete_project(
        project_id=project.id,
        from_facts=["origin"],
        description="Solution found",
        worker="solver"
    )
    
    assert result is not None
    completed_project, completion_intent = result
    
    assert completed_project.status == "completed"
    assert completion_intent.to == "goal"
    assert completion_intent.description == "Solution found"


@pytest.mark.asyncio
async def test_reopen_project(storage):
    """Test reopening a completed project."""
    project = await storage.create_project("Test", "Origin", "Goal")
    await storage.complete_project(project.id, ["origin"], "Solution", "solver")
    
    # Reopen with feedback
    result = await storage.reopen_project(
        project_id=project.id,
        description="Solution needs refinement",
        creator="reviewer"
    )
    
    assert result is not None
    reopened_project, feedback_fact, feedback_intent = result
    
    assert reopened_project.status == "active"
    assert feedback_fact.description == "Solution needs refinement"
    assert feedback_intent.description == "external_feedback"


@pytest.mark.asyncio
async def test_export_yaml(storage):
    """Test YAML export."""
    project = await storage.create_project(
        "Export Test",
        "Starting point",
        "End goal",
        hints=[{"content": "Hint 1", "creator": "user"}]
    )
    
    await storage.create_intent(project.id, ["origin"], "Explore", "user")
    
    yaml_content = await storage.export_yaml(project.id)
    assert yaml_content is not None
    assert "project:" in yaml_content
    assert "facts:" in yaml_content
    assert "intents:" in yaml_content


@pytest.mark.asyncio
async def test_delete_project(storage):
    """Test project deletion cascades to related data."""
    project = await storage.create_project("Test", "Origin", "Goal")
    await storage.create_intent(project.id, ["origin"], "Explore", "user")
    await storage.create_hint(project.id, "Hint", "user")
    
    deleted = await storage.delete_project(project.id)
    assert deleted is True
    
    # Verify project is gone
    retrieved = await storage.get_project(project.id)
    assert retrieved is None


@pytest.mark.asyncio
async def test_update_project_status(storage):
    """Test status transitions."""
    project = await storage.create_project("Test", "Origin", "Goal")
    
    # Stop project
    stopped = await storage.update_project_status(project.id, "stopped")
    assert stopped.status == "stopped"
    
    # Reactivate
    reactivated = await storage.update_project_status(project.id, "active")
    assert reactivated.status == "active"
    
    # Cannot complete directly via status update
    with pytest.raises(ValueError):
        await storage.update_project_status(project.id, "completed")


@pytest.mark.asyncio
async def test_intent_validation(storage):
    """Test intent validation rules."""
    project = await storage.create_project("Test", "Origin", "Goal")
    
    # Cannot create intent from 'goal'
    with pytest.raises(ValueError, match="cannot contain 'goal'"):
        await storage.create_intent(
            project_id=project.id,
            from_facts=["goal"],
            description="Invalid",
            creator="user"
        )
