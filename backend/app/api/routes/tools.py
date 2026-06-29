from fastapi import APIRouter, Depends

from backend.app.dependencies import require_subscription
from backend.app.services.tools import list_tools

router = APIRouter()


@router.get("/api/tools")
def tools_list(_user=Depends(require_subscription)):
    return {"tools": list_tools()}
