"""
Split Webhook Bridge — Collega il webhook Alchemy allo SplitExecutor.

Scopo
─────
Quando arriva una TX in entrata al Master wallet di un cliente, verifica
se esiste uno SplitContract attivo per quel (wallet, chain). Se sì, esegue
il piano di distribuzione multi-wallet (SplitEngine + SplitExecutor) e
ritorna `handled=True`, così il normale flusso delle ForwardingRule
viene saltato per quella TX.

Integrazione
────────────
È un modulo ADDITIVO: non tocca né sweep_service né forwarding_models.
Viene chiamato dal webhook handler (`sweeper_routes._process_alchemy_activity`)
prima della dispatch Celery / direct path. Se ritorna `handled=True`,
il chiamante fa `continue` sull'iterazione della TX.

Invarianti
──────────
  • Split ha PRIORITÀ sulle ForwardingRule per lo stesso master_wallet.
  • Idempotente per (contract_id, source_tx_hash): una stessa TX non viene
    mai ri-splittata (verifica su SplitExecution prima di eseguire).
  • Fail-mode: se l'esecuzione fallisce parzialmente, i fondi non inviati
    restano nel Master (lo SplitExecutor gestisce `partial_failure`).
  • Dopo la prima esecuzione il contratto viene lockato (`is_locked=True`).
  • Se nessun SplitContract matcha → ritorna None (non tocca il db).

Signer
──────
`_RpcSigner` è un adapter minimale conforme all'interfaccia attesa da
SplitExecutor (`send_native` / `send_erc20`). Usa lo stesso pattern di
`sweep_service.execute_single_sweep`: `eth_account.Account.from_key` +
`rpc_manager.consensus_call` + `estimate_gas_cost`.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db.session import async_session
from app.models.split_models import (
    SplitContract,
    SplitExecution,
    SplitRecipient,  # noqa: F401 — imported for relationship materialization
)
from app.services.split_engine import compute_split
from app.services.split_executor import SplitExecutor, DuplicateSplitExecution

logger = logging.getLogger("rsend.split_bridge")


# ═══════════════════════════════════════════════════════════
#  Private key loader (duplica logica minima di sweep_service
#  per evitare import circolari al top-level)
# ═══════════════════════════════════════════════════════════

def _load_private_key() -> Optional[str]:
    """Legge la sweep_private_key dalle settings, con validazione formato.

    .. deprecated::
        Prefer ``get_signer()`` from ``key_manager``. Kept for backward-compat.
    """
    try:
        pk = get_settings().sweep_private_key
    except Exception:
        return None
    if not pk or not pk.startswith("0x") or len(pk) != 66:
        return None
    return pk


# ═══════════════════════════════════════════════════════════
#  _RpcSigner — adapter conforme all'interfaccia SplitExecutor
# ═══════════════════════════════════════════════════════════

class _RpcSigner:
    """
    Firma e invia TX tramite ``key_manager.AbstractSigner`` + rpc_manager.

    Interfaccia conforme a quanto atteso da
    `app.services.split_executor.SplitExecutor`:
      - `async send_native(to: str, value: int) -> str`
      - `async send_erc20(token_address: str, to: str, amount: int) -> str`

    Supporta sia LocalSigner (dev) che KMSSigner (prod)
    in base a ``SIGNER_MODE``.
    """

    def __init__(self, chain_id: int, *, private_key: Optional[str] = None):
        from app.services.rpc_manager import get_rpc_manager

        if private_key:
            # Backward-compat: accept explicit key (e.g. deposit child keys)
            from app.services.key_manager import LocalSigner
            self._signer = LocalSigner(private_key=private_key)
        else:
            from app.services.key_manager import get_signer
            self._signer = get_signer()

        # Use the atomic Redis NonceManager only for the SHARED hot wallet
        # (no explicit key). Deposit child keys are per-address (≈1 TX each),
        # so their raw 'pending' read stays as-is.
        self._managed_nonce = private_key is None
        self._rpc = get_rpc_manager(chain_id)
        self._chain_id = chain_id
        self._cached_address: Optional[str] = None

    async def get_address(self) -> str:
        if not self._cached_address:
            self._cached_address = await self._signer.get_address()
        return self._cached_address

    async def _next_nonce(self) -> int:
        """Next nonce for the signer.

        Shared hot wallet → atomic Redis NonceManager (cross-worker safe).
        Deposit child key → raw 'pending' read (per-address, single TX).
        """
        if self._managed_nonce:
            from app.services.nonce_manager import get_nonce_manager, NonceError
            nm = get_nonce_manager(self._chain_id)
            try:
                return await nm.get_next()
            except NonceError:
                await nm.initialize()
                return await nm.get_next()

        addr = await self.get_address()
        raw = await self._rpc.consensus_call(
            "eth_getTransactionCount",
            [addr, "pending"],
        )
        return int(raw, 16)

    async def _build_and_send(self, est_params: dict, tx_body: dict) -> str:
        """
        Stima gas + firma + invia la TX.

        est_params: dict con "from/to/value/data" per `eth_estimateGas`
                    (match del formato usato da sweep_service).
        tx_body:    dict con i campi della TX da firmare (NO from).
        """
        from app.models.forwarding_models import GasStrategy
        from app.services.sweep_service import estimate_gas_cost

        gas_limit, gas_gwei, _cost_eth, fee_params = await estimate_gas_cost(
            self._chain_id, GasStrategy.normal, est_params,
        )
        nonce = await self._next_nonce()

        tx = {
            **tx_body,
            "gas": gas_limit,
            "nonce": nonce,
            "chainId": self._chain_id,
            **fee_params,
        }

        raw_tx = await self._signer.sign_transaction(tx)
        raw_hex = "0x" + raw_tx.hex()
        result = await self._rpc.send_raw_transaction(raw_hex)
        tx_hash = result if isinstance(result, str) else ""

        logger.info(
            "[split_bridge] TX sent on chain=%d gas=%d gwei=%.3f hash=%s",
            self._chain_id, gas_limit, gas_gwei, (tx_hash or "")[:16],
        )
        return tx_hash

    async def send_native(self, to: str, value: int) -> str:
        value_int = int(value)
        addr = await self.get_address()
        est_params = {
            "from": addr,
            "to": to,
            "value": hex(value_int),
        }
        tx_body = {
            "to": to,
            "value": value_int,
        }
        return await self._build_and_send(est_params, tx_body)

    async def send_erc20(self, token_address: str, to: str, amount: int) -> str:
        # ERC-20 transfer(address,uint256) calldata
        method_id = "a9059cbb"
        to_clean = to[2:] if to.lower().startswith("0x") else to
        to_padded = to_clean.lower().rjust(64, "0")
        amount_padded = hex(int(amount))[2:].rjust(64, "0")
        data = "0x" + method_id + to_padded + amount_padded

        addr = await self.get_address()
        est_params = {
            "from": addr,
            "to": token_address,
            "data": data,
        }
        tx_body = {
            "to": token_address,
            "value": 0,
            "data": data,
        }
        return await self._build_and_send(est_params, tx_body)


# ═══════════════════════════════════════════════════════════
#  Main entrypoint — maybe_execute_split
# ═══════════════════════════════════════════════════════════

def _human_to_raw(amount_human, decimals: int) -> int:
    """Converte un importo human-readable (float/str) in unità minime (int)."""
    factor = Decimal(10) ** int(decimals)
    return int(Decimal(str(amount_human)) * factor)


async def _find_active_contract(
    db: AsyncSession,
    master_wallet_lower: str,
    chain_id: int,
) -> Optional[SplitContract]:
    """
    Trova lo SplitContract attivo con versione più alta per (wallet, chain).
    Carica i recipient eager per evitare N+1 successivi.
    """
    q = (
        select(SplitContract)
        .options(selectinload(SplitContract.recipients))
        .where(
            SplitContract.master_wallet == master_wallet_lower,
            SplitContract.is_active == True,  # noqa: E712
            SplitContract.chain_id == chain_id,
        )
        .order_by(desc(SplitContract.version))
        .limit(1)
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def _find_existing_execution(
    db: AsyncSession,
    contract_id: int,
    source_tx_hash: str,
) -> Optional[SplitExecution]:
    """Dedup: cerca una SplitExecution già esistente per (contract_id, source_tx_hash)."""
    q = (
        select(SplitExecution)
        .where(
            SplitExecution.contract_id == contract_id,
            SplitExecution.source_tx_hash == source_tx_hash,
        )
        .limit(1)
    )
    result = await db.execute(q)
    return result.scalar_one_or_none()


async def maybe_execute_split(
    *,
    to_addr: str,
    chain_id: int,
    amount_human: float,
    token_symbol: str,
    token_decimals: int,
    source_tx_hash: str,
) -> Optional[dict]:
    """
    Tenta di eseguire uno split per una TX in entrata al Master wallet.

    Ritorna:
      * `None` se nessuno SplitContract matcha (il chiamante deve continuare
        con il normale flusso di forwarding rules).
      * `dict` con forma:
          {
              "handled": bool,
              "contract_id": int,
              "execution_id": Optional[int],
              "status": str,
              "duplicate": bool,  # opzionale
              "error": str,       # opzionale (se handled=False per errore)
          }
        Se `handled=True`, il chiamante DEVE saltare il forwarding normale.
        Se `handled=False` + `error` valorizzato, c'è stato un errore di
        configurazione (no signer / no recipients / plan invalid) — il
        chiamante può decidere se cadere sul forwarding normale o meno.
        Per sicurezza, raccomandato: se `handled=False` NON cadere sul
        forwarding (fail-closed).

    Args:
        to_addr: Address del Master wallet (recipient della TX in entrata).
        chain_id: Chain ID su cui è arrivata la TX.
        amount_human: Importo in unità human (float), come da payload Alchemy.
        token_symbol: Simbolo del token in entrata ("ETH", "USDC", ...).
        token_decimals: Decimali del token in entrata.
        source_tx_hash: Hash della TX che ha triggerato lo split.
    """
    to_lower = (to_addr or "").lower()
    if not to_lower or not source_tx_hash:
        return None

    try:
        amount_raw = _human_to_raw(amount_human, token_decimals)
    except Exception as e:
        logger.warning(
            "[split_bridge] amount conversion failed (%r decimals=%d): %s",
            amount_human, token_decimals, e,
        )
        return None

    if amount_raw <= 0:
        return None

    async with async_session() as db:
        # ── Trova il contratto attivo ───────────────────────
        contract = await _find_active_contract(db, to_lower, chain_id)
        if contract is None:
            return None  # Nessuno split → forwarding rules normali

        logger.info(
            "[split_bridge] SplitContract #%d matched wallet=%s chain=%d version=%d tx=%s",
            contract.id, to_lower, chain_id, contract.version,
            source_tx_hash[:16],
        )

        # ── Idempotency: stessa TX già processata? ──────────
        existing = await _find_existing_execution(db, contract.id, source_tx_hash)
        if existing is not None:
            logger.info(
                "[split_bridge] Duplicate split skipped: contract=%d execution=%d "
                "tx=%s status=%s",
                contract.id, existing.id, source_tx_hash[:16], existing.status,
            )
            return {
                "handled": True,
                "contract_id": contract.id,
                "execution_id": existing.id,
                "status": existing.status,
                "duplicate": True,
            }

        # ── Signer (via key_manager — supports local + KMS) ──
        from app.services.key_manager import get_signer, SignerError

        try:
            _km_signer = get_signer()
        except SignerError as e:
            logger.error(
                "[split_bridge] Signer not available — cannot execute "
                "split for contract #%d: %s",
                contract.id, e,
            )
            return {
                "handled": False,
                "contract_id": contract.id,
                "execution_id": None,
                "status": "no_signer",
                "error": f"Signer not configured: {e}",
            }

        # ── Recipients list (solo attivi) ───────────────────
        recipients = [
            {
                "wallet_address": r.wallet_address,
                "label": r.label or "",
                "role": r.role or "recipient",
                "share_bps": int(r.share_bps),
                "position": int(r.position),
            }
            for r in contract.recipients
            if r.is_active
        ]
        if len(recipients) < 2:
            logger.warning(
                "[split_bridge] Contract #%d has %d active recipients (need ≥ 2) — "
                "skipping split",
                contract.id, len(recipients),
            )
            return {
                "handled": False,
                "contract_id": contract.id,
                "execution_id": None,
                "status": "no_recipients",
                "error": f"active recipients = {len(recipients)}",
            }

        # ── Build plan ──────────────────────────────────────
        try:
            plan = compute_split(
                input_amount=amount_raw,
                recipients=recipients,
                rsend_fee_bps=int(contract.rsend_fee_bps or 50),
                token=token_symbol,
                decimals=int(token_decimals),
            )
        except ValueError as e:
            logger.error(
                "[split_bridge] Plan build failed for contract #%d: %s",
                contract.id, e,
            )
            return {
                "handled": False,
                "contract_id": contract.id,
                "execution_id": None,
                "status": "plan_invalid",
                "error": str(e),
            }

        plan.contract_id = contract.id
        plan.client_id = contract.client_id

        # ── Execute ─────────────────────────────────────────
        signer = _RpcSigner(chain_id=chain_id)
        executor = SplitExecutor(
            signer=signer,
            rpc_client=signer._rpc,
            db_session=db,
        )

        try:
            execution = await executor.execute(plan, source_tx_hash=source_tx_hash)
        except DuplicateSplitExecution:
            # Concurrent/duplicate delivery already created the execution (DB
            # unique constraint uq_split_exec_contract_srctx). NO TX was sent on
            # this path — re-read the winning execution and return an idempotent
            # duplicate result (fail-closed: handled=True skips forwarding).
            existing = await _find_existing_execution(db, contract.id, source_tx_hash)
            logger.info(
                "[split_bridge] Duplicate split prevented by DB constraint: "
                "contract=%d tx=%s execution=%s",
                contract.id, source_tx_hash[:16],
                existing.id if existing else None,
            )
            return {
                "handled": True,
                "contract_id": contract.id,
                "execution_id": existing.id if existing else None,
                "status": existing.status if existing else "duplicate",
                "duplicate": True,
            }
        except Exception as exec_err:
            logger.exception(
                "[split_bridge] Execution raised for contract #%d tx=%s: %s",
                contract.id, source_tx_hash[:16], exec_err,
            )
            # Fail-closed: handled=True, lo split è stato TENTATO
            return {
                "handled": True,
                "contract_id": contract.id,
                "execution_id": None,
                "status": "failed",
                "error": str(exec_err),
            }

        # ── Lock contract dopo la prima esecuzione ──────────
        try:
            if not contract.is_locked:
                contract.is_locked = True
                contract.locked_at = datetime.utcnow()
                await db.commit()
                logger.info(
                    "[split_bridge] Contract #%d locked after first execution",
                    contract.id,
                )
        except Exception as lock_err:
            logger.warning(
                "[split_bridge] Failed to lock contract #%d after execution: %s",
                contract.id, lock_err,
            )
            try:
                await db.rollback()
            except Exception:
                pass

        logger.info(
            "[split_bridge] Split done contract=%d execution=%d status=%s tx=%s",
            contract.id, execution.id, execution.status, source_tx_hash[:16],
        )
        return {
            "handled": True,
            "contract_id": contract.id,
            "execution_id": execution.id,
            "status": execution.status,
        }
