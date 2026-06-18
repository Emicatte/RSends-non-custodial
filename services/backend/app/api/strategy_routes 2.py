from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


class ConditionInput(BaseModel):
    type: str
    value: Optional[str] = None
    min: Optional[str] = None
    max: Optional[str] = None
    # Flexible extra fields
    model_config = {"extra": "allow"}


class ActionInput(BaseModel):
    type: str
    params: dict = {}


class CreateStrategyRequest(BaseModel):
    owner_address: str
    name: str
    description: str = ""
    chain_family: str = "evm"
    chain_id: Optional[str] = None
    conditions: list[ConditionInput]
    actions: list[ActionInput]
    priority: int = 0
    max_executions_per_day: Optional[int] = None
    cooldown_seconds: int = 60


@router.post("/")
async def create_strategy(req: CreateStrategyRequest):
    """Create a new automation strategy."""
    # TODO: validate condition types, action types
    # TODO: save to DB
    return {"status": "created", "strategy_id": 1}


@router.get("/")
async def list_strategies(owner: str):
    """List all strategies for an owner."""
    # TODO: query DB
    return {"strategies": []}


@router.patch("/{strategy_id}")
async def update_strategy(strategy_id: int, updates: dict):
    """Update strategy (toggle, modify conditions/actions)."""
    return {"status": "updated"}


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: int):
    """Delete a strategy."""
    return {"status": "deleted"}


@router.post("/simulate")
async def simulate_strategy(req: CreateStrategyRequest, test_context: dict):
    """
    Dry-run: test if conditions would match against a sample context.
    Useful for testing before activating a strategy.
    """
    from app.services.strategy_engine import StrategyEvaluator
    evaluator = StrategyEvaluator()
    matches = evaluator.evaluate_conditions(
        [c.model_dump() for c in req.conditions],
        test_context,
    )
    return {"would_match": matches, "actions": [a.model_dump() for a in req.actions] if matches else []}
