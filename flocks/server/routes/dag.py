"""
DAG API 路由桥接 — 薄层接入 Flocks Server。

将 dag/routes/ 下的子路由包装为 Flocks Server 标准的 APIRouter。
"""

from fastapi import APIRouter

from flocks.dag.store import GraphStore
from flocks.dag.routes.projects import create_projects_router
from flocks.dag.routes.graph import create_graph_router
from flocks.dag.routes.tasks import create_tasks_router

# 全局引用，由 lifespan 中 init_dag() 设置
_store: GraphStore = None
_orchestrator = None
_session_manager = None
_bus = None
_project_analyzer = None


def init_dag_routes(
    store: GraphStore,
    orchestrator,
    session_manager=None,
    bus=None,
    project_analyzer=None,
) -> APIRouter:
    """初始化 DAG 路由（由 lifespan 调用）"""
    global _store, _orchestrator, _session_manager, _bus, _project_analyzer
    _store = store
    _orchestrator = orchestrator
    _session_manager = session_manager
    _bus = bus
    _project_analyzer = project_analyzer

    router = APIRouter(prefix="/dag", tags=["DAG"])
    router.include_router(create_projects_router(store, project_analyzer))
    router.include_router(create_graph_router(store))
    router.include_router(create_tasks_router(store, orchestrator, session_manager, bus))
    return router
