"""
Execution engine API routes.
Plan preview + execute cross-chain operations.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/execution", tags=["execution"])


class CrossChainRequest(BaseModel):
    owner: str
    source_chain: str        # e.g. "tron-mainnet", "8453", "mainnet-beta"
    source_token: str        # e.g. "USDT", "ETH"
    target_chain: str
    target_token: str
    destinations: list[dict]  # [{"address": "0x...", "percent": 70}, ...]
    notify: bool = True


@router.post("/plan")
async def create_plan(req: CrossChainRequest):
    """Create a cross-chain execution plan (dry run — no execution)."""
    from app.services.execution_engine import build_cross_chain_plan

    plan = build_cross_chain_plan(
        owner=req.owner,
        source_chain=req.source_chain,
        source_token=req.source_token,
        target_chain=req.target_chain,
        target_token=req.target_token,
        destinations=req.destinations,
        notify=req.notify,
    )
    return {
        "plan_id": plan.id,
        "steps": [
            {"type": s.type, "chain": s.chain_id, "status": s.status, "params": s.params}
            for s in plan.steps
        ],
        "total_steps": len(plan.steps),
    }


@router.post("/plan/{plan_id}/execute")
async def execute_plan(plan_id: str):
    """Execute a previously created plan."""
    # TODO: retrieve plan from DB, instantiate engine, execute
    raise HTTPException(501, "Execution not yet implemented — plan preview only")


@router.get("/plan/{plan_id}")
async def get_plan_status(plan_id: str):
    """Get current status of an execution plan."""
    raise HTTPException(501, "Plan tracking not yet implemented")
