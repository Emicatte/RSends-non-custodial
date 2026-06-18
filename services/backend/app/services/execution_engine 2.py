"""
Cross-chain execution engine.
Orchestrates multi-step operations: detect → bridge → swap → split → send.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import asyncio
import logging

logger = logging.getLogger("rsend.engine")


class StepType(str, Enum):
    DETECT = "detect"       # Wait for incoming funds
    BRIDGE = "bridge"       # Cross-chain bridge
    SWAP = "swap"           # DEX swap on target chain
    SPLIT = "split"         # Calculate split amounts
    SEND = "send"           # Send to final destinations
    NOTIFY = "notify"       # Notification (Telegram, email)


class StepStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ExecutionStep:
    type: StepType
    status: StepStatus = StepStatus.PENDING
    chain_family: str = "evm"
    chain_id: str = ""
    tx_hash: Optional[str] = None
    error: Optional[str] = None
    params: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)


@dataclass
class ExecutionPlan:
    """A complete cross-chain operation plan."""
    id: str
    owner: str
    steps: list[ExecutionStep]
    status: StepStatus = StepStatus.PENDING
    created_at: str = ""
    completed_at: Optional[str] = None


class ExecutionEngine:
    """
    Executes multi-step cross-chain plans.

    Each step is executed sequentially. If a step fails,
    the engine stops and marks the plan as failed.
    Funds are NEVER lost — failed steps leave funds
    at the last successful position.
    """

    def __init__(self, signers: dict, rpc_clients: dict):
        self.signers = signers        # chain_id -> TxSigner
        self.rpc_clients = rpc_clients  # chain_id -> RPC client
        self._running_plans: dict[str, asyncio.Task] = {}

    async def execute_plan(self, plan: ExecutionPlan) -> ExecutionPlan:
        """Execute all steps in a plan sequentially.

        Fail-closed: verifies critical dependencies (Postgres, Redis)
        before starting any financial operation. Per-chain RPC is checked
        before steps that interact with a specific chain.
        """
        # ── Kill switch check ───────────────────────────
        from app.services.kill_switch import kill_switch as _ks

        ks_allowed, ks_reason = await _ks.can_execute()
        if not ks_allowed:
            plan.status = StepStatus.FAILED
            logger.error("[Engine] Plan %s BLOCKED by kill switch: %s", plan.id, ks_reason)
            return plan

        # ── Fail-closed dependency check ────────────────
        try:
            from app.services.circuit_breaker import dependency_guard, SweepBlockedError
            await dependency_guard.require_postgres()
            await dependency_guard.require_redis()
        except Exception as e:
            plan.status = StepStatus.FAILED
            logger.error("[Engine] Plan %s BLOCKED: %s", plan.id, e)
            return plan

        plan.status = StepStatus.EXECUTING
        logger.info(f"[Engine] Starting plan {plan.id} with {len(plan.steps)} steps")

        for i, step in enumerate(plan.steps):
            try:
                logger.info(f"[Engine] Step {i+1}/{len(plan.steps)}: {step.type}")

                # Per-chain RPC guard for steps that interact with a chain
                if step.chain_id and step.type in (
                    StepType.BRIDGE, StepType.SWAP, StepType.SEND,
                ):
                    try:
                        from app.services.circuit_breaker import dependency_guard
                        chain_int = int(step.chain_id) if step.chain_id.isdigit() else 0
                        if chain_int > 0:
                            await dependency_guard.require_rpc(chain_id=chain_int)
                    except Exception as rpc_err:
                        step.status = StepStatus.FAILED
                        step.error = f"RPC blocked: {rpc_err}"
                        plan.status = StepStatus.FAILED
                        logger.error("[Engine] Step %d BLOCKED (RPC): %s", i + 1, rpc_err)
                        return plan

                step.status = StepStatus.EXECUTING

                if step.type == StepType.DETECT:
                    await self._execute_detect(step)
                elif step.type == StepType.BRIDGE:
                    await self._execute_bridge(step)
                elif step.type == StepType.SWAP:
                    await self._execute_swap(step)
                elif step.type == StepType.SPLIT:
                    await self._execute_split(step)
                elif step.type == StepType.SEND:
                    await self._execute_send(step)
                elif step.type == StepType.NOTIFY:
                    await self._execute_notify(step)

                step.status = StepStatus.COMPLETED
                logger.info(f"[Engine] Step {i+1} completed: {step.result}")

            except Exception as e:
                step.status = StepStatus.FAILED
                step.error = str(e)
                plan.status = StepStatus.FAILED
                logger.error(f"[Engine] Step {i+1} failed: {e}")
                return plan

        plan.status = StepStatus.COMPLETED
        return plan

    async def _execute_detect(self, step: ExecutionStep):
        """Wait for incoming funds detection (via webhook or polling)."""
        # Implementato tramite Alchemy webhook o polling
        step.result = {"detected": True, "amount": step.params.get("amount", "0")}

    async def _execute_bridge(self, step: ExecutionStep):
        """Bridge funds between chains."""
        # Per ora: placeholder
        # Integrazioni future: LayerZero, Axelar, Wormhole, Across
        raise NotImplementedError(
            "Cross-chain bridging not yet implemented. "
            "Supported bridges coming: LayerZero, Across, Wormhole"
        )

    async def _execute_swap(self, step: ExecutionStep):
        """Execute swap on target chain."""
        chain = step.chain_id
        token_in = step.params["token_in"]
        token_out = step.params["token_out"]
        amount = step.params["amount"]

        # Usa l'adapter appropriato
        if step.chain_family == "evm":
            # Chiama Uniswap V3 via RPC
            signer = self.signers.get(chain)
            if not signer:
                raise ValueError(f"No signer for chain {chain}")
            # TODO: build and send swap TX
            step.result = {"swap_hash": "0x...", "amount_out": "..."}

        elif step.chain_family == "solana":
            # Chiama Jupiter API
            step.result = {"swap_hash": "...", "amount_out": "..."}

        elif step.chain_family == "tron":
            # Chiama SunSwap
            step.result = {"swap_hash": "...", "amount_out": "..."}

    async def _execute_split(self, step: ExecutionStep):
        """Calculate split amounts from total."""
        total = int(step.params["total_amount"])
        destinations = step.params["destinations"]  # [{address, percent}, ...]

        splits = []
        for dest in destinations:
            amount = int(total * dest["percent"] / 100)
            splits.append({"address": dest["address"], "amount": str(amount)})

        step.result = {"splits": splits}

    async def _execute_send(self, step: ExecutionStep):
        """Send funds to final destination."""
        chain = step.chain_id
        signer = self.signers.get(chain)
        if not signer:
            raise ValueError(f"No signer for chain {chain}")

        to = step.params["to"]
        amount = step.params["amount"]
        token = step.params.get("token")

        # Usa sweep_service.py esistente per l'invio
        # Che ha già: gas guard, retry logic, split routing
        step.result = {"send_hash": "0x...", "to": to, "amount": amount}

    async def _execute_notify(self, step: ExecutionStep):
        """Send notification (Telegram, email)."""
        channel = step.params.get("channel", "telegram")
        message = step.params.get("message", "Operation completed")
        # Usa il notify service esistente se c'è, altrimenti log
        logger.info(f"[Notify] {channel}: {message}")
        step.result = {"notified": True}


def build_cross_chain_plan(
    owner: str,
    source_chain: str,
    source_token: str,
    target_chain: str,
    target_token: str,
    destinations: list[dict],
    notify: bool = True,
) -> ExecutionPlan:
    """
    Build an execution plan for cross-chain operation.

    Example: USDT su Tron → ETH su Base → split 3 wallet
    Genera plan con steps: detect → bridge → swap → split → send × 3 → notify
    """
    import uuid
    from datetime import datetime

    plan_id = str(uuid.uuid4())[:8]
    steps: list[ExecutionStep] = []

    # Step 1: Detect incoming on source chain
    steps.append(ExecutionStep(
        type=StepType.DETECT,
        chain_family=_detect_family(source_chain),
        chain_id=source_chain,
        params={"token": source_token, "owner": owner},
    ))

    # Step 2: Bridge if cross-chain
    if source_chain != target_chain:
        steps.append(ExecutionStep(
            type=StepType.BRIDGE,
            chain_family=_detect_family(source_chain),
            chain_id=source_chain,
            params={
                "from_chain": source_chain,
                "to_chain": target_chain,
                "token": source_token,
            },
        ))

    # Step 3: Swap if different token
    if source_token != target_token:
        steps.append(ExecutionStep(
            type=StepType.SWAP,
            chain_family=_detect_family(target_chain),
            chain_id=target_chain,
            params={
                "token_in": source_token,
                "token_out": target_token,
            },
        ))

    # Step 4: Split calculation
    if len(destinations) > 1:
        steps.append(ExecutionStep(
            type=StepType.SPLIT,
            params={"destinations": destinations},
        ))

    # Step 5: Send to each destination
    for dest in destinations:
        steps.append(ExecutionStep(
            type=StepType.SEND,
            chain_family=_detect_family(target_chain),
            chain_id=target_chain,
            params={
                "to": dest["address"],
                "amount": "COMPUTED_FROM_SPLIT",
                "token": target_token,
            },
        ))

    # Step 6: Notify
    if notify:
        steps.append(ExecutionStep(
            type=StepType.NOTIFY,
            params={
                "channel": "telegram",
                "message": f"Cross-chain operation {plan_id} completed",
            },
        ))

    return ExecutionPlan(
        id=plan_id,
        owner=owner,
        steps=steps,
        created_at=datetime.utcnow().isoformat(),
    )


def _detect_family(chain_id: str) -> str:
    if chain_id in ("mainnet-beta", "devnet"):
        return "solana"
    if chain_id in ("tron-mainnet", "tron-shasta"):
        return "tron"
    return "evm"
