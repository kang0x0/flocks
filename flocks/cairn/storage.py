"""
Cairn storage layer.

Provides SQLite persistence for Cairn projects, facts, intents, and hints.
Integrates with Flocks' existing Storage abstraction.

Database schema:
- cairn_projects: Project metadata and status
- cairn_facts: Immutable fact records
- cairn_intents: Exploration intent records with heartbeat tracking
- cairn_hints: External strategy suggestions
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from flocks.cairn.models import (
    ExportYamlFact,
    ExportYamlHint,
    ExportYamlIntent,
    Fact,
    Hint,
    Intent,
    Project,
    ProjectDetail,
    ProjectSummary,
    ReasonLease,
)
from flocks.utils.log import Log

log = Log.create(service="cairn.storage")

# Database file location (in Flocks data directory)
DB_PATH = Path.home() / ".flocks" / "cairn.db"


class CairnStorage:
    """SQLite-based storage for Cairn data."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return
        
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Enable WAL mode for better concurrency
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            
            # Create tables
            await self._create_tables(db)
            await self._create_indexes(db)
            
            await db.commit()
        
        self._initialized = True
        log.info("cairn.storage.initialized", {"db_path": str(self.db_path)})
    
    async def _create_tables(self, db: aiosqlite.Connection) -> None:
        """Create database tables."""
        
        # Projects table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cairn_projects (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'stopped', 'completed')),
                origin_fact_id TEXT NOT NULL,
                goal_fact_id TEXT NOT NULL,
                reason_worker TEXT,
                reason_trigger TEXT,
                reason_started_at TIMESTAMP,
                reason_last_heartbeat_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (origin_fact_id, id) REFERENCES cairn_facts(id, project_id),
                FOREIGN KEY (goal_fact_id, id) REFERENCES cairn_facts(id, project_id)
            )
        """)
        
        # Facts table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cairn_facts (
                id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id, project_id),
                FOREIGN KEY (project_id) REFERENCES cairn_projects(id) ON DELETE CASCADE
            )
        """)
        
        # Intents table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cairn_intents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                from_facts TEXT NOT NULL,
                to_fact_id TEXT,
                description TEXT NOT NULL,
                creator TEXT NOT NULL,
                worker TEXT,
                last_heartbeat_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                concluded_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES cairn_projects(id) ON DELETE CASCADE,
                FOREIGN KEY (to_fact_id, project_id) REFERENCES cairn_facts(id, project_id)
            )
        """)
        
        # Hints table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cairn_hints (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                content TEXT NOT NULL,
                creator TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES cairn_projects(id) ON DELETE CASCADE
            )
        """)
    
    async def _create_indexes(self, db: aiosqlite.Connection) -> None:
        """Create indexes for common queries."""
        
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_intents_project_worker ON cairn_intents(project_id, worker)",
            "CREATE INDEX IF NOT EXISTS idx_intents_unclaimed ON cairn_intents(project_id) WHERE worker IS NULL AND to_fact_id IS NULL",
            "CREATE INDEX IF NOT EXISTS idx_facts_project ON cairn_facts(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_hints_project ON cairn_hints(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_projects_status ON cairn_projects(status)",
        ]
        
        for index_sql in indexes:
            await db.execute(index_sql)
    
    # ========================================================================
    # Project operations
    # ========================================================================
    
    async def create_project(
        self,
        title: str,
        origin: str,
        goal: str,
        hints: Optional[List[Dict[str, str]]] = None,
    ) -> Project:
        """Create a new project with origin and goal facts."""
        await self.initialize()
        
        import ulid
        
        project_id = f"proj_{ulid.new()}"
        now = datetime.now(timezone.utc)
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Create origin and goal facts
            await db.execute(
                "INSERT INTO cairn_facts (id, project_id, description, created_at) VALUES (?, ?, ?, ?)",
                ("origin", project_id, origin, now.isoformat())
            )
            await db.execute(
                "INSERT INTO cairn_facts (id, project_id, description, created_at) VALUES (?, ?, ?, ?)",
                ("goal", project_id, goal, now.isoformat())
            )
            
            # Create project
            await db.execute(
                """INSERT INTO cairn_projects 
                   (id, title, status, origin_fact_id, goal_fact_id, created_at, updated_at)
                   VALUES (?, ?, 'active', 'origin', 'goal', ?, ?)""",
                (project_id, title, now.isoformat(), now.isoformat())
            )
            
            # Create initial hints if provided
            if hints:
                for hint_data in hints:
                    hint_id = f"h{ulid.new()}"
                    await db.execute(
                        "INSERT INTO cairn_hints (id, project_id, content, creator, created_at) VALUES (?, ?, ?, ?, ?)",
                        (hint_id, project_id, hint_data["content"], hint_data["creator"], now.isoformat())
                    )
            
            await db.commit()
        
        log.info("cairn.project.created", {"id": project_id, "title": title})
        
        return Project(
            id=project_id,
            title=title,
            status="active",
            origin_fact_id="origin",
            goal_fact_id="goal",
            created_at=now,
            updated_at=now,
        )
    
    async def get_project(self, project_id: str) -> Optional[Project]:
        """Get project by ID."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM cairn_projects WHERE id = ?",
                (project_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_project(row)
    
    async def get_project_detail(self, project_id: str) -> Optional[ProjectDetail]:
        """Get complete project with facts, intents, and hints."""
        await self.initialize()
        
        project = await self.get_project(project_id)
        if not project:
            return None
        
        facts = await self.get_facts(project_id)
        intents = await self.get_intents(project_id)
        hints = await self.get_hints(project_id)
        
        return ProjectDetail(
            project=project,
            facts=facts,
            intents=intents,
            hints=hints,
        )
    
    async def list_projects(self) -> List[ProjectSummary]:
        """List all projects with summary statistics."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                """SELECT p.*,
                          (SELECT COUNT(*) FROM cairn_facts WHERE project_id = p.id) as fact_count,
                          (SELECT COUNT(*) FROM cairn_intents WHERE project_id = p.id) as intent_count,
                          (SELECT COUNT(*) FROM cairn_intents WHERE project_id = p.id AND worker IS NOT NULL AND to_fact_id IS NULL) as working_intent_count,
                          (SELECT COUNT(*) FROM cairn_intents WHERE project_id = p.id AND worker IS NULL AND to_fact_id IS NULL) as unclaimed_intent_count,
                          (SELECT COUNT(*) FROM cairn_hints WHERE project_id = p.id) as hint_count
                   FROM cairn_projects p
                   ORDER BY p.created_at DESC"""
            )
            rows = await cursor.fetchall()
            
            return [self._row_to_summary(row) for row in rows]
    
    async def update_project_title(self, project_id: str, title: str) -> Optional[Project]:
        """Update project title."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute(
                "UPDATE cairn_projects SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, project_id)
            )
            await db.commit()
        
        return await self.get_project(project_id)
    
    async def update_project_status(self, project_id: str, status: str) -> Optional[Project]:
        """Update project status (only active <-> stopped)."""
        if status not in ("active", "stopped"):
            raise ValueError(f"Invalid status: {status}. Use reopen API for completed projects.")
        
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            # If stopping, clear all open intent workers and reason lease
            if status == "stopped":
                await db.execute(
                    "UPDATE cairn_intents SET worker = NULL WHERE project_id = ? AND to_fact_id IS NULL",
                    (project_id,)
                )
                await db.execute(
                    "UPDATE cairn_projects SET reason_worker = NULL, reason_trigger = NULL, reason_started_at = NULL, reason_last_heartbeat_at = NULL WHERE id = ?",
                    (project_id,)
                )
            
            await db.execute(
                "UPDATE cairn_projects SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, project_id)
            )
            await db.commit()
        
        return await self.get_project(project_id)
    
    async def delete_project(self, project_id: str) -> bool:
        """Delete project and all associated data."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            cursor = await db.execute(
                "DELETE FROM cairn_projects WHERE id = ?",
                (project_id,)
            )
            await db.commit()
            
            deleted = cursor.rowcount > 0
        
        if deleted:
            log.info("cairn.project.deleted", {"id": project_id})
        
        return deleted
    
    # ========================================================================
    # Fact operations
    # ========================================================================
    
    async def get_facts(self, project_id: str) -> List[Fact]:
        """Get all facts for a project."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM cairn_facts WHERE project_id = ? ORDER BY created_at",
                (project_id,)
            )
            rows = await cursor.fetchall()
            
            return [self._row_to_fact(row) for row in rows]
    
    # ========================================================================
    # Intent operations
    # ========================================================================
    
    async def create_intent(
        self,
        project_id: str,
        from_facts: List[str],
        description: str,
        creator: str,
        worker: Optional[str] = None,
    ) -> Intent:
        """Create a new intent."""
        await self.initialize()
        
        import ulid
        
        intent_id = f"i{ulid.new()}"
        now = datetime.now(timezone.utc)
        
        # Validate: from cannot contain 'goal'
        if "goal" in from_facts:
            raise ValueError("Intent 'from' cannot contain 'goal'")
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute(
                """INSERT INTO cairn_intents 
                   (id, project_id, from_facts, description, creator, worker, last_heartbeat_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    intent_id,
                    project_id,
                    json.dumps(from_facts),
                    description,
                    creator,
                    worker,
                    now.isoformat() if worker else None,
                    now.isoformat(),
                )
            )
            await db.commit()
        
        log.info("cairn.intent.created", {"id": intent_id, "project": project_id})
        
        return Intent(
            id=intent_id,
            project_id=project_id,
            from_=from_facts,
            description=description,
            creator=creator,
            worker=worker,
            last_heartbeat_at=now if worker else None,
            created_at=now,
        )
    
    async def get_intents(self, project_id: str) -> List[Intent]:
        """Get all intents for a project."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE project_id = ? ORDER BY created_at",
                (project_id,)
            )
            rows = await cursor.fetchall()
            
            return [self._row_to_intent(row) for row in rows]
    
    async def heartbeat_intent(
        self,
        project_id: str,
        intent_id: str,
        worker: str,
    ) -> Optional[Intent]:
        """Heartbeat an intent (claim or renew)."""
        await self.initialize()
        
        now = datetime.now(timezone.utc)
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Check if intent exists and is not concluded
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE id = ? AND project_id = ? AND to_fact_id IS NULL",
                (intent_id, project_id)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            current_worker = row["worker"]
            
            # Check claim rules
            if current_worker is not None and current_worker != worker:
                # Check if current worker's heartbeat has timed out (5 minutes default)
                last_hb = row["last_heartbeat_at"]
                if last_hb:
                    from datetime import timedelta
                    last_hb_time = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                    if now - last_hb_time < timedelta(minutes=5):
                        return None  # Still claimed by another worker
            
            # Update worker and heartbeat
            await db.execute(
                "UPDATE cairn_intents SET worker = ?, last_heartbeat_at = ? WHERE id = ?",
                (worker, now.isoformat(), intent_id)
            )
            await db.commit()
            
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE id = ?",
                (intent_id,)
            )
            updated_row = await cursor.fetchone()
            
            return self._row_to_intent(updated_row)
    
    async def release_intent(
        self,
        project_id: str,
        intent_id: str,
        worker: str,
    ) -> Optional[Intent]:
        """Release an intent (make it unclaimed)."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Only current worker can release
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE id = ? AND project_id = ? AND worker = ? AND to_fact_id IS NULL",
                (intent_id, project_id, worker)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            await db.execute(
                "UPDATE cairn_intents SET worker = NULL WHERE id = ?",
                (intent_id,)
            )
            await db.commit()
            
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE id = ?",
                (intent_id,)
            )
            updated_row = await cursor.fetchone()
            
            return self._row_to_intent(updated_row)
    
    async def conclude_intent(
        self,
        project_id: str,
        intent_id: str,
        worker: str,
        fact_description: str,
    ) -> Optional[tuple[Fact, Intent]]:
        """Conclude an intent with a new fact."""
        await self.initialize()
        
        import ulid
        
        fact_id = f"f{ulid.new()}"
        now = datetime.now(timezone.utc)
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Check if intent exists, is not concluded, and worker matches
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE id = ? AND project_id = ? AND to_fact_id IS NULL",
                (intent_id, project_id)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            current_worker = row["worker"]
            if current_worker is not None and current_worker != worker:
                return None
            
            # Create new fact
            await db.execute(
                "INSERT INTO cairn_facts (id, project_id, description, created_at) VALUES (?, ?, ?, ?)",
                (fact_id, project_id, fact_description, now.isoformat())
            )
            
            # Update intent
            await db.execute(
                "UPDATE cairn_intents SET to_fact_id = ?, worker = ?, concluded_at = ? WHERE id = ?",
                (fact_id, worker, now.isoformat(), intent_id)
            )
            
            await db.commit()
            
            # Fetch updated records
            cursor = await db.execute(
                "SELECT * FROM cairn_facts WHERE id = ? AND project_id = ?",
                (fact_id, project_id)
            )
            fact_row = await cursor.fetchone()
            
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE id = ?",
                (intent_id,)
            )
            intent_row = await cursor.fetchone()
            
            fact = self._row_to_fact(fact_row)
            intent = self._row_to_intent(intent_row)
            
            log.info("cairn.intent.concluded", {"intent_id": intent_id, "fact_id": fact_id})
            
            return (fact, intent)
    
    # ========================================================================
    # Hint operations
    # ========================================================================
    
    async def create_hint(
        self,
        project_id: str,
        content: str,
        creator: str,
    ) -> Hint:
        """Create a new hint."""
        await self.initialize()
        
        import ulid
        
        hint_id = f"h{ulid.new()}"
        now = datetime.now(timezone.utc)
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.execute(
                "INSERT INTO cairn_hints (id, project_id, content, creator, created_at) VALUES (?, ?, ?, ?, ?)",
                (hint_id, project_id, content, creator, now.isoformat())
            )
            await db.commit()
        
        return Hint(
            id=hint_id,
            project_id=project_id,
            content=content,
            creator=creator,
            created_at=now,
        )
    
    async def get_hints(self, project_id: str) -> List[Hint]:
        """Get all hints for a project."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM cairn_hints WHERE project_id = ? ORDER BY created_at",
                (project_id,)
            )
            rows = await cursor.fetchall()
            
            return [self._row_to_hint(row) for row in rows]
    
    # ========================================================================
    # Reason lease operations
    # ========================================================================
    
    async def claim_reason(
        self,
        project_id: str,
        worker: str,
        trigger: str,
    ) -> Optional[Project]:
        """Claim project-level reason lease."""
        await self.initialize()
        
        now = datetime.now(timezone.utc)
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Check current status
            cursor = await db.execute(
                "SELECT * FROM cairn_projects WHERE id = ? AND status = 'active'",
                (project_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            current_worker = row["reason_worker"]
            
            # Check if already claimed by another worker
            if current_worker is not None and current_worker != worker:
                # Check timeout (5 minutes default)
                last_hb = row["reason_last_heartbeat_at"]
                if last_hb:
                    from datetime import timedelta
                    last_hb_time = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                    if now - last_hb_time < timedelta(minutes=5):
                        return None  # Still claimed
            
            # Claim or renew
            await db.execute(
                """UPDATE cairn_projects 
                   SET reason_worker = ?, reason_trigger = ?, reason_started_at = COALESCE(reason_started_at, ?), reason_last_heartbeat_at = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (worker, trigger, now.isoformat(), now.isoformat(), project_id)
            )
            await db.commit()
            
            return await self.get_project(project_id)
    
    async def heartbeat_reason(
        self,
        project_id: str,
        worker: str,
    ) -> Optional[Project]:
        """Heartbeat reason lease."""
        await self.initialize()
        
        now = datetime.now(timezone.utc)
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM cairn_projects WHERE id = ? AND reason_worker = ?",
                (project_id, worker)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            await db.execute(
                "UPDATE cairn_projects SET reason_last_heartbeat_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (now.isoformat(), project_id)
            )
            await db.commit()
            
            return await self.get_project(project_id)
    
    async def release_reason(
        self,
        project_id: str,
        worker: str,
    ) -> Optional[Project]:
        """Release reason lease."""
        await self.initialize()
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            cursor = await db.execute(
                "SELECT * FROM cairn_projects WHERE id = ? AND reason_worker = ?",
                (project_id, worker)
            )
            row = await cursor.fetchone()
            
            if not row:
                # Already released or never claimed
                return await self.get_project(project_id)
            
            await db.execute(
                """UPDATE cairn_projects 
                   SET reason_worker = NULL, reason_trigger = NULL, reason_started_at = NULL, reason_last_heartbeat_at = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (project_id,)
            )
            await db.commit()
            
            return await self.get_project(project_id)
    
    # ========================================================================
    # Complete/Reopen operations
    # ========================================================================
    
    async def complete_project(
        self,
        project_id: str,
        from_facts: List[str],
        description: str,
        worker: str,
    ) -> Optional[tuple[Project, Intent]]:
        """Mark project as completed by creating completion intent."""
        await self.initialize()
        
        import ulid
        
        intent_id = f"i{ulid.new()}"
        now = datetime.now(timezone.utc)
        
        # Validate: from cannot contain 'goal'
        if "goal" in from_facts:
            raise ValueError("Complete 'from' cannot contain 'goal'")
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Check project is active
            cursor = await db.execute(
                "SELECT * FROM cairn_projects WHERE id = ? AND status = 'active'",
                (project_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            # Create completion intent (from facts -> goal)
            await db.execute(
                """INSERT INTO cairn_intents 
                   (id, project_id, from_facts, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at)
                   VALUES (?, ?, ?, 'goal', ?, ?, ?, ?, ?, ?)""",
                (
                    intent_id,
                    project_id,
                    json.dumps(from_facts),
                    description,
                    worker,
                    worker,
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                )
            )
            
            # Update project status and clear reason lease
            await db.execute(
                """UPDATE cairn_projects 
                   SET status = 'completed', reason_worker = NULL, reason_trigger = NULL, reason_started_at = NULL, reason_last_heartbeat_at = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (project_id,)
            )
            
            await db.commit()
            
            # Fetch updated records
            project = await self.get_project(project_id)
            
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE id = ?",
                (intent_id,)
            )
            intent_row = await cursor.fetchone()
            
            intent = self._row_to_intent(intent_row)
            
            log.info("cairn.project.completed", {"id": project_id})
            
            return (project, intent)
    
    async def reopen_project(
        self,
        project_id: str,
        description: str,
        creator: str,
    ) -> Optional[tuple[Project, Fact, Intent]]:
        """Reopen a completed project with feedback."""
        await self.initialize()
        
        import ulid
        
        fact_id = f"f{ulid.new()}"
        intent_id = f"i{ulid.new()}"
        now = datetime.now(timezone.utc)
        
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            
            # Check project is completed
            cursor = await db.execute(
                "SELECT * FROM cairn_projects WHERE id = ? AND status = 'completed'",
                (project_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                return None
            
            # Find the completion intent (to_fact_id = 'goal')
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE project_id = ? AND to_fact_id = 'goal'",
                (project_id,)
            )
            completion_intent = await cursor.fetchone()
            
            if not completion_intent:
                return None
            
            original_from = json.loads(completion_intent["from_facts"])
            
            # Delete completion intent
            await db.execute(
                "DELETE FROM cairn_intents WHERE id = ?",
                (completion_intent["id"],)
            )
            
            # Create feedback fact
            await db.execute(
                "INSERT INTO cairn_facts (id, project_id, description, created_at) VALUES (?, ?, ?, ?)",
                (fact_id, project_id, description, now.isoformat())
            )
            
            # Create external_feedback intent
            await db.execute(
                """INSERT INTO cairn_intents 
                   (id, project_id, from_facts, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at)
                   VALUES (?, ?, ?, ?, 'external_feedback', ?, ?, ?, ?, ?)""",
                (
                    intent_id,
                    project_id,
                    json.dumps(original_from),
                    fact_id,
                    creator,
                    creator,
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                )
            )
            
            # Update project status back to active
            await db.execute(
                """UPDATE cairn_projects 
                   SET status = 'active', reason_worker = NULL, reason_trigger = NULL, reason_started_at = NULL, reason_last_heartbeat_at = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (project_id,)
            )
            
            await db.commit()
            
            # Fetch updated records
            project = await self.get_project(project_id)
            
            cursor = await db.execute(
                "SELECT * FROM cairn_facts WHERE id = ? AND project_id = ?",
                (fact_id, project_id)
            )
            fact_row = await cursor.fetchone()
            
            cursor = await db.execute(
                "SELECT * FROM cairn_intents WHERE id = ?",
                (intent_id,)
            )
            intent_row = await cursor.fetchone()
            
            fact = self._row_to_fact(fact_row)
            intent = self._row_to_intent(intent_row)
            
            log.info("cairn.project.reopened", {"id": project_id})
            
            return (project, fact, intent)
    
    # ========================================================================
    # Export operations
    # ========================================================================
    
    async def export_yaml(self, project_id: str) -> Optional[str]:
        """Export project as YAML format."""
        await self.initialize()
        
        detail = await self.get_project_detail(project_id)
        if not detail:
            return None
        
        import yaml
        
        # Build YAML structure
        yaml_data = {
            "project": {
                "title": detail.project.title,
                "origin": next((f.description for f in detail.facts if f.id == "origin"), ""),
                "goal": next((f.description for f in detail.facts if f.id == "goal"), ""),
            },
            "hints": [
                {
                    "content": h.content,
                    "creator": h.creator,
                    "created_at": h.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for h in detail.hints
            ],
            "facts": [
                {
                    "id": f.id,
                    "description": f.description,
                }
                for f in detail.facts
            ],
            "intents": [
                {
                    "from": i.from_,
                    "to": i.to,
                    "description": i.description,
                    "creator": i.creator,
                    "worker": i.worker,
                    "created_at": i.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "concluded_at": i.concluded_at.strftime("%Y-%m-%d %H:%M:%S") if i.concluded_at else None,
                }
                for i in detail.intents
            ],
        }
        
        return yaml.dump(yaml_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # ========================================================================
    # Helper methods
    # ========================================================================
    
    def _row_to_project(self, row: aiosqlite.Row) -> Project:
        """Convert database row to Project model."""
        reason = None
        if row["reason_worker"]:
            reason = ReasonLease(
                worker=row["reason_worker"],
                trigger=row["reason_trigger"] or "",
                started_at=datetime.fromisoformat(row["reason_started_at"].replace("Z", "+00:00")) if row["reason_started_at"] else datetime.utcnow(),
                last_heartbeat_at=datetime.fromisoformat(row["reason_last_heartbeat_at"].replace("Z", "+00:00")) if row["reason_last_heartbeat_at"] else datetime.utcnow(),
            )
        
        return Project(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            origin_fact_id=row["origin_fact_id"],
            goal_fact_id=row["goal_fact_id"],
            reason=reason,
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
            updated_at=datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")),
        )
    
    def _row_to_summary(self, row: aiosqlite.Row) -> ProjectSummary:
        """Convert database row to ProjectSummary model."""
        reason = None
        if row["reason_worker"]:
            reason = ReasonLease(
                worker=row["reason_worker"],
                trigger=row["reason_trigger"] or "",
                started_at=datetime.fromisoformat(row["reason_started_at"].replace("Z", "+00:00")) if row["reason_started_at"] else datetime.utcnow(),
                last_heartbeat_at=datetime.fromisoformat(row["reason_last_heartbeat_at"].replace("Z", "+00:00")) if row["reason_last_heartbeat_at"] else datetime.utcnow(),
            )
        
        return ProjectSummary(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
            reason=reason,
            fact_count=row["fact_count"],
            intent_count=row["intent_count"],
            working_intent_count=row["working_intent_count"],
            unclaimed_intent_count=row["unclaimed_intent_count"],
            hint_count=row["hint_count"],
        )
    
    def _row_to_fact(self, row: aiosqlite.Row) -> Fact:
        """Convert database row to Fact model."""
        return Fact(
            id=row["id"],
            project_id=row["project_id"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        )
    
    def _row_to_intent(self, row: aiosqlite.Row) -> Intent:
        """Convert database row to Intent model."""
        return Intent(
            id=row["id"],
            project_id=row["project_id"],
            from_=json.loads(row["from_facts"]),
            to=row["to_fact_id"],
            description=row["description"],
            creator=row["creator"],
            worker=row["worker"],
            last_heartbeat_at=datetime.fromisoformat(row["last_heartbeat_at"].replace("Z", "+00:00")) if row["last_heartbeat_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
            concluded_at=datetime.fromisoformat(row["concluded_at"].replace("Z", "+00:00")) if row["concluded_at"] else None,
        )
    
    def _row_to_hint(self, row: aiosqlite.Row) -> Hint:
        """Convert database row to Hint model."""
        return Hint(
            id=row["id"],
            project_id=row["project_id"],
            content=row["content"],
            creator=row["creator"],
            created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")),
        )


# Global storage instance
_storage: Optional[CairnStorage] = None


def get_storage() -> CairnStorage:
    """Get global Cairn storage instance."""
    global _storage
    if _storage is None:
        _storage = CairnStorage()
    return _storage
