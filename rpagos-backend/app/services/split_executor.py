"""
Split Executor — Esegue il piano di distribuzione on-chain.

Tutte le TX partono dal Master wallet.
NO catene (A→B→C). Solo A→D, A→B, A→C parallele/sequenziali.

Fail-mode:
  - Se alcune TX falliscono, lo stato diventa `partial_failure`
    e i fondi non inviati restano nel Master wallet.
  - Nessun rollback on-chain possibile: lo stato DB riflette
    esattamente cosa è stato inviato.
"""
from datetime import datetime
from typing import Optional
import asyncio
import json
import logging

from sqlalchemy.exc import IntegrityError

from app.services.split_engine import SplitPlan, SplitOutput
from app.services.aml_exceptions import AMLBlockedError
from app.models.split_models import SplitExecution

logger = logging.getLogger("rsend.split_exec")


class DuplicateSplitExecution(Exception):
    """Raised when a SplitExecution already exists for (contract_id, source_tx_hash).

    Triggered by the DB unique constraint `uq_split_exec_contract_srctx` when a
    concurrent/duplicate webhook delivery tries to execute the same split.
    The INSERT is rejected BEFORE any on-chain transfer is sent, so no funds
    move on the duplicate path — the caller should treat it as idempotent.
    """

    def __init__(self, contract_id: int, source_tx_hash: str):
        self.contract_id = contract_id
        self.source_tx_hash = source_tx_hash
        super().__init__(
            f"duplicate split execution: contract={contract_id} "
            f"tx={source_tx_hash[:16]}"
        )

# ──────────────────────────────────────────────────────────────
# Rough EUR conversion for AML thresholds.
# Stablecoins → 1:1. For ETH/WETH a conservative estimate is used;
# real-time price would come from the oracle, but for AML gating
# a ballpark is sufficient (over-estimating is safer).
# ──────────────────────────────────────────────────────────────
_STABLECOINS = {"USDC", "USDT", "DAI"}
_ETH_EUR_ESTIMATE = 3000.0  # conservative; updated manually or via config


def _wei_to_eur(amount_wei: int, token: str, decimals: int) -> float:
    """Best-effort conversion from wei to EUR for AML threshold checks."""
    units = amount_wei / (10 ** decimals)
    if token.upper() in _STABLECOINS:
        return units  # 1 stablecoin ≈ 1 EUR
    if token.upper() in ("ETH", "WETH"):
        return units * _ETH_EUR_ESTIMATE
    return units  # fallback: treat as 1:1


from app.services.kill_switch import kill_switch, auto_stop


class SplitExecutor:
    """Esegue un SplitPlan inviando N transazioni dal Master wallet."""

    def __init__(self, signer, rpc_client, db_session):
        """
        Args:
            signer: oggetto con metodi async `send_native(to, value)` e
                    `send_erc20(token_address, to, amount)`, entrambi
                    ritornano il tx_hash come stringa hex "0x...".
            rpc_client: client RPC (non usato direttamente qui ma iniettabile
                    per future letture/conferme on-chain).
            db_session: AsyncSession SQLAlchemy già aperta dal chiamante.
        """
        self.signer = signer
        self.rpc = rpc_client
        self.db = db_session
        # Ref guard per impedire doppie esecuzioni dello stesso executor
        self._in_flight: bool = False

    async def execute(self, plan: SplitPlan, source_tx_hash: str) -> SplitExecution:
        """
        Esegue tutte le distribuzioni di un SplitPlan.

        Strategia: tenta tutte le TX. Se alcune falliscono, registra
        `partial_failure` (i fondi non inviati restano nel Master).

        Raises:
            RuntimeError: se kill-switch blocca o se execute è già in corso
        """
        # Ref guard anti-doppio-invio
        if self._in_flight:
            raise RuntimeError("SplitExecutor.execute already in progress")
        self._in_flight = True

        execution: Optional[SplitExecution] = None
        try:
            # ── Kill switch check ───────────────────────────
            allowed, reason = await kill_switch.can_execute(plan.client_id)
            if not allowed:
                raise RuntimeError(f"Blocked by kill switch: {reason}")

            # ── AML Gate: screen BEFORE any on-chain TX ────
            await self._aml_gate(plan)

            # ── Crea record esecuzione ──────────────────────
            execution = SplitExecution(
                contract_id=plan.contract_id,
                source_tx_hash=source_tx_hash,
                input_amount=str(plan.input_amount),
                input_token=plan.token,
                input_decimals=plan.decimals,
                status="executing",
                started_at=datetime.utcnow(),
            )
            self.db.add(execution)
            # Idempotency gate (C1a): the unique constraint on
            # (contract_id, source_tx_hash) makes this flush the atomic,
            # cross-worker point of no return. If a concurrent/previous
            # delivery already inserted this execution, the flush raises
            # IntegrityError HERE — before any _send_single — so the
            # duplicate path sends ZERO transactions.
            try:
                await self.db.flush()
            except IntegrityError:
                await self.db.rollback()
                raise DuplicateSplitExecution(plan.contract_id, source_tx_hash)

            # ── Esegui tutte le TX ──────────────────────────
            results = []
            all_success = True

            for output in plan.outputs:
                try:
                    tx_hash = await self._send_single(output, plan.token, plan.decimals)
                    results.append({
                        "wallet": output.wallet,
                        "label": output.label,
                        "share_bps": output.share_bps,
                        "amount": str(output.amount),
                        "tx_hash": tx_hash,
                        "status": "sent",
                    })
                    logger.info(
                        "[Split] Sent %s %s to %s (%.2f%%) — TX: %s",
                        output.amount, plan.token, output.wallet,
                        output.share_bps / 100, tx_hash,
                    )
                    try:
                        auto_stop.record_success(plan.client_id)
                    except Exception as _as_err:
                        logger.debug("[split_exec] auto_stop.record_success shim err: %s", _as_err)

                except Exception as e:
                    all_success = False
                    results.append({
                        "wallet": output.wallet,
                        "label": output.label,
                        "share_bps": output.share_bps,
                        "amount": str(output.amount),
                        "tx_hash": None,
                        "status": "failed",
                        "error": str(e),
                    })
                    logger.error("[Split] FAILED to send to %s: %s", output.wallet, e)
                    try:
                        auto_stop.record_failure(plan.client_id)
                    except Exception as _as_err:
                        logger.debug("[split_exec] auto_stop.record_failure shim err: %s", _as_err)

            # ── Aggiorna execution record ──────────────────
            execution.distribution_detail = json.dumps(results)
            execution.rsend_fee = str(plan.rsend_fee)
            execution.remainder = str(plan.remainder)
            execution.completed_at = datetime.utcnow()

            sent_total = sum(int(r["amount"]) for r in results if r["status"] == "sent")
            execution.total_distributed = str(sent_total)

            if all_success:
                execution.status = "completed"
            elif any(r["status"] == "sent" for r in results):
                execution.status = "partial_failure"
            else:
                execution.status = "failed"

            await self.db.commit()
            return execution

        except Exception:
            # In caso di eccezione non gestita (kill-switch block, DB error, ecc.)
            # proviamo a rollbackare la sessione per non lasciarla in stato sporco.
            try:
                await self.db.rollback()
            except Exception as _rb_err:
                logger.debug("[split_exec] rollback error: %s", _rb_err)
            raise
        finally:
            self._in_flight = False

    async def _send_single(self, output: SplitOutput, token: str, decimals: int) -> str:
        """Invia una singola TX dal Master al destinatario.

        Delega alla signature astratta `signer.send_native` / `signer.send_erc20`.
        Il wiring concreto (LocalSigner/KMSSigner) è responsabilità del chiamante
        — vedi `sweep_service.py` per il pattern di firma basato su
        `eth_account.Account.from_key` + `rpc.consensus_call`.
        """
        if token.upper() in ("ETH", "WETH"):
            # Native transfer
            tx_hash = await self.signer.send_native(
                to=output.wallet,
                value=output.amount,
            )
        else:
            # ERC-20 transfer (il Master deve già possedere i fondi)
            tx_hash = await self.signer.send_erc20(
                token_address=self._get_token_address(token),
                to=output.wallet,
                amount=output.amount,
            )

        return tx_hash

    def _get_token_address(self, symbol: str) -> str:
        """Mappa symbol → contract address per la chain corrente.

        TODO: sostituire con lookup da contractRegistry/addresses per chain_id.
        Hardcoded Base mainnet per ora.
        """
        TOKEN_MAP = {
            "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "USDT": "0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2",
            "DAI":  "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
        }
        addr = TOKEN_MAP.get(symbol.upper())
        if not addr:
            raise ValueError(f"Unknown token: {symbol}")
        return addr

    async def _aml_gate(self, plan: SplitPlan) -> None:
        """Pre-execution AML check: screens all recipients + anti-structuring.

        Blocks the ENTIRE plan if any recipient is sanctioned.
        Flags (but allows) if threshold/structuring patterns detected.
        """
        from app.services.aml_service import is_blacklisted, check_split_plan

        # 1. Screen ALL recipient addresses against sanctions
        blocked_recipients: list[dict] = []
        for output in plan.outputs:
            is_blocked, reason = await is_blacklisted(output.wallet)
            if is_blocked:
                blocked_recipients.append({
                    "address": output.wallet,
                    "reason": reason,
                })

        if blocked_recipients:
            logger.error(
                "[split_exec] AML BLOCKED: %d recipient(s) on sanctions list",
                len(blocked_recipients),
                extra={"blocked": blocked_recipients, "client_id": plan.client_id},
            )
            raise AMLBlockedError(
                f"Split blocked: {len(blocked_recipients)} recipient(s) "
                f"failed AML screening"
            )

        # 2. Anti-structuring: check aggregate amounts
        recipients = [o.wallet for o in plan.outputs]
        amounts_eur = [
            _wei_to_eur(o.amount, plan.token, plan.decimals)
            for o in plan.outputs
        ]

        aml_result = await check_split_plan(
            source_wallet=plan.client_id,
            recipients=recipients,
            amounts_eur=amounts_eur,
        )

        if aml_result.requires_manual_review:
            total_eur = sum(amounts_eur)
            logger.warning(
                "[split_exec] AML FLAG: split requires manual review "
                "(€%.2f across %d recipients, risk=%s)",
                total_eur, len(recipients), aml_result.risk_level,
            )
