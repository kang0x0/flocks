"""
DAG 项目管理 API。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from flocks.dag.store import GraphStore
from flocks.dag.models import PreAnalysisResult
from flocks.utils.log import Log

logger = Log.create(service=__name__)


# ---- Request Models ----

class AnalyzeRequest(BaseModel):
    user_input: str


class CreateProjectRequest(BaseModel):
    title: str
    origin: str
    goal: str
    description: str = ""


class HintRequest(BaseModel):
    content: str
    hint_type: str = "guidance"


class FactRequest(BaseModel):
    id: str
    content: str
    fact_type: str = "discovery"
    confidence: float = 1.0
    evidence: Optional[str] = None


class IntentRequest(BaseModel):
    id: str
    description: str
    source_fact_ids: list = []
    priority: int = 0


# ---- Router Factory ----

def create_projects_router(
    store: GraphStore,
    project_analyzer=None,  # ProjectAnalyzer
    config: dict = None,
) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["DAG Projects"])

    # ---- 预分析 ----

    @router.post("/analyze", response_model=PreAnalysisResult)
    async def analyze_user_input(req: AnalyzeRequest):
        """AI 预分析用户输入，提取 origin 和 goal"""
        if project_analyzer is None:
            raise HTTPException(503, "预分析服务未初始化")
        result = await project_analyzer.analyze(req.user_input)
        return result

    # ---- 项目 CRUD ----

    @router.post("")
    async def create_project(req: CreateProjectRequest):
        """创建 DAG 项目"""
        project_id = await store.create_project(
            title=req.title,
            origin_content=req.origin,
            goal_content=req.goal,
            description=req.description,
        )
        return {"project_id": project_id}

    @router.get("")
    async def list_projects(status: Optional[str] = None):
        """列出所有项目"""
        projects = await store.list_projects(status)
        return {"projects": projects, "count": len(projects)}

    @router.get("/{project_id}")
    async def get_project(project_id: str):
        """获取项目详情"""
        project = await store.get_project(project_id)
        if not project:
            raise HTTPException(404, "项目不存在")
        return project

    @router.post("/{project_id}/stop")
    async def stop_project(project_id: str):
        """暂停项目"""
        from flocks.dag.models import ProjectStatus
        await store.update_status(project_id, ProjectStatus.STOPPED)
        return {"status": "stopped"}

    @router.post("/{project_id}/resume")
    async def resume_project(project_id: str):
        """恢复项目"""
        from flocks.dag.models import ProjectStatus
        await store.update_status(project_id, ProjectStatus.ACTIVE)
        return {"status": "active"}

    @router.delete("/{project_id}")
    async def delete_project(project_id: str):
        """删除项目（标记为 completed）"""
        from flocks.dag.models import ProjectStatus
        await store.update_status(project_id, ProjectStatus.COMPLETED)
        return {"status": "deleted"}

    # ---- Fact 管理 ----

    @router.get("/{project_id}/facts")
    async def list_facts(project_id: str):
        facts = await store.get_facts(project_id)
        return {"facts": [f.model_dump(mode="json") for f in facts]}

    @router.post("/{project_id}/facts")
    async def add_fact(project_id: str, req: FactRequest):
        from flocks.dag.models import FactNode
        fact = FactNode(
            id=req.id,
            project_id=project_id,
            content=req.content,
            fact_type=req.fact_type,
            confidence=req.confidence,
            evidence=req.evidence,
        )
        await store.add_fact(fact)
        return fact.model_dump(mode="json")

    # ---- Intent 管理 ----

    @router.get("/{project_id}/intents")
    async def list_intents(project_id: str):
        intents = await store.get_intents(project_id)
        return {"intents": [i.model_dump(mode="json") for i in intents]}

    @router.post("/{project_id}/intents")
    async def create_intent(project_id: str, req: IntentRequest):
        from flocks.dag.models import IntentEdge
        intent = IntentEdge(
            id=req.id,
            project_id=project_id,
            description=req.description,
            source_fact_ids=req.source_fact_ids,
            priority=req.priority,
        )
        await store.create_intent(intent)
        return intent.model_dump(mode="json")

    # ---- Hint 管理 ----

    @router.get("/{project_id}/hints")
    async def list_hints(project_id: str):
        hints = await store.get_unread_hints(project_id)
        return {"hints": hints}

    @router.post("/{project_id}/hints")
    async def add_hint(project_id: str, req: HintRequest):
        hint_id = await store.add_hint(
            project_id, req.content, req.hint_type
        )
        return {"hint_id": hint_id}

    return router
