"""
DAG HTTP API 路由。

返回 dag_router (APIRouter)，由 Flocks Server 通过 app.include_router() 注册。
"""

from fastapi import APIRouter

from flocks.dag.store import GraphStore
from flocks.dag.routes.projects import create_projects_router
from flocks.dag.routes.graph import create_graph_router
from flocks.dag.routes.tasks import create_tasks_router


def create_dag_router(
    store: GraphStore,
    orchestrator,  # DagOrchestrator
    config: dict,
    session_manager=None,
    project_analyzer=None,
    bus=None,
) -> APIRouter:
    """创建 DAG 模块的 APIRouter（包含所有子路由）"""
    router = APIRouter(prefix="", tags=["DAG"])

    # 注册子路由
    router.include_router(create_projects_router(store, project_analyzer, config))
    router.include_router(create_graph_router(store))
    router.include_router(create_tasks_router(store, orchestrator, session_manager, bus))

    return router
