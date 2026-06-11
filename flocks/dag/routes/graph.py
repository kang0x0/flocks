"""
DAG 图操作 API — 图快照、Mermaid 导出、统计。
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from flocks.dag.store import GraphStore
from flocks.dag.graph import FactIntentGraph
from flocks.utils.log import Log

logger = Log.create(service=__name__)


def create_graph_router(store: GraphStore) -> APIRouter:
    router = APIRouter(prefix="", tags=["DAG Graph"])

    @router.get("/projects/{project_id}/graph")
    async def get_graph_snapshot(project_id: str):
        """获取图快照（JSON）"""
        try:
            snapshot = await store.export_snapshot(project_id)
            return snapshot.model_dump(mode='json')
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            logger.error("graph.snapshot_error", {"project_id": project_id, "error": str(e)})
            raise HTTPException(500, f"Internal error: {e}")

    @router.get("/projects/{project_id}/graph/mermaid", response_class=PlainTextResponse)
    async def export_mermaid(project_id: str):
        """导出 Mermaid 流程图文本"""
        try:
            snapshot = await store.export_snapshot(project_id)
            mermaid = FactIntentGraph.to_mermaid(snapshot)
            return mermaid
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            logger.error("graph.mermaid_error", {"project_id": project_id, "error": str(e)})
            raise HTTPException(500, f"Internal error: {e}")

    @router.get("/projects/{project_id}/statistics")
    async def get_statistics(project_id: str):
        """获取项目统计"""
        try:
            return await store.get_statistics(project_id)
        except ValueError as e:
            raise HTTPException(404, str(e))

    return router
