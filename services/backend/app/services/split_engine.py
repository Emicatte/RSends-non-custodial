"""
Multi-Wallet Split Engine

Regole fondamentali:
1. Percentuali SEMPRE in basis points (interi). 10000 = 100.00%
2. Somma BPS di tutti i recipient DEVE essere esattamente 10000
3. Calcoli in unità minime del token (wei, satoshi, etc.) — MAI float
4. Il "remainder" da rounding va al recipient con share più alta (primary)
5. Tutte le TX partono dal Master wallet — NO catene
6. O tutte le TX vanno a buon fine, o rollback logico
"""
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger("rsend.split")


@dataclass
class SplitOutput:
    """Risultato del calcolo split per un singolo destinatario."""
    wallet: str
    label: str
    role: str
    share_bps: int
    amount: int         # In unità minime (wei, smallest unit)
    position: int


@dataclass
class SplitPlan:
    """Piano completo di distribuzione."""
    contract_id: int
    client_id: str
    input_amount: int               # Importo lordo in unità minime
    rsend_fee: int                  # Fee RSend in unità minime
    distributable: int              # input_amount - rsend_fee
    outputs: list                   # list[SplitOutput]
    remainder: int                  # Resto da rounding (assegnato al primary)
    token: str
    decimals: int
    total_check: int                # Deve essere == distributable
    rsend_fee_bps: int = 50         # BPS usati per calcolare rsend_fee


def validate_recipients(recipients: list) -> tuple:
    """
    Valida una lista di recipient prima di salvare.

    Args:
        recipients: lista di dict {wallet_address, share_bps, [label], [role], [position]}

    Returns:
        (is_valid: bool, error_message: str)
    """
    if not recipients or len(recipients) < 2:
        return False, "At least 2 recipients required"

    if len(recipients) > 20:
        return False, "Maximum 20 recipients allowed"

    total_bps = 0
    addresses_seen = set()

    for i, r in enumerate(recipients):
        wallet = (r.get("wallet_address") or "").lower()
        bps = r.get("share_bps", 0)

        # Tipo — deve essere intero puro (no float, no bool)
        if not isinstance(bps, int) or isinstance(bps, bool):
            return False, f"Recipient {i}: share_bps must be integer, got {type(bps).__name__}"

        # Range
        if bps <= 0:
            return False, f"Recipient {i}: share_bps must be > 0, got {bps}"
        if bps > 10000:
            return False, f"Recipient {i}: share_bps must be <= 10000, got {bps}"

        # Address valido (formato minimo 0x + 40 hex)
        if not wallet or len(wallet) != 42 or not wallet.startswith("0x"):
            return False, f"Recipient {i}: invalid wallet address"

        # Duplicati
        if wallet in addresses_seen:
            return False, f"Recipient {i}: duplicate wallet {wallet}"
        addresses_seen.add(wallet)

        total_bps += bps

    # Somma ESATTA — mai "close enough"
    if total_bps != 10000:
        return False, f"Total share must be exactly 10000 BPS (100.00%), got {total_bps}"

    return True, "OK"


def compute_split(
    input_amount: int,
    recipients: list,  # [{"wallet_address": "0x...", "share_bps": 9500, "label": "...", "role": "...", "position": 0}]
    rsend_fee_bps: int = 50,
    token: str = "USDC",
    decimals: int = 6,
) -> SplitPlan:
    """
    Calcola la distribuzione esatta di un importo tra N recipient.

    Tutta la matematica è in INTERI (unità minime del token).
    Il remainder da rounding va al recipient in position più bassa (primary).

    Args:
        input_amount: Importo lordo in unità minime (es: 100_000_000 per 100 USDC)
        recipients: Lista destinatari con share_bps
        rsend_fee_bps: Fee RSend in BPS (50 = 0.50%)
        token: Simbolo token
        decimals: Decimali del token

    Returns:
        SplitPlan con la distribuzione esatta

    Raises:
        ValueError: su config invalida o input_amount <= 0
    """
    # Validazione recipient (bps integer, somma == 10000, no duplicati, address ok)
    valid, err = validate_recipients(recipients)
    if not valid:
        raise ValueError(f"Invalid split config: {err}")

    if not isinstance(input_amount, int) or isinstance(input_amount, bool):
        raise ValueError(f"input_amount must be integer, got {type(input_amount).__name__}")
    if input_amount <= 0:
        raise ValueError(f"Input amount must be > 0, got {input_amount}")

    # Validazione fee RSend
    if not isinstance(rsend_fee_bps, int) or isinstance(rsend_fee_bps, bool):
        raise ValueError(f"rsend_fee_bps must be integer, got {type(rsend_fee_bps).__name__}")
    if rsend_fee_bps < 0 or rsend_fee_bps > 10000:
        raise ValueError(f"rsend_fee_bps must be in [0, 10000], got {rsend_fee_bps}")

    # 1. Calcola fee RSend (in unità minime, troncamento intero)
    rsend_fee = (input_amount * rsend_fee_bps) // 10000

    # 2. Importo distribuibile
    distributable = input_amount - rsend_fee

    # 3. Calcola quota per ogni recipient (troncamento, non arrotondamento)
    outputs = []
    total_allocated = 0

    # Ordina per position (stabile: a parità di position mantiene l'ordine di input)
    sorted_recipients = sorted(
        enumerate(recipients),
        key=lambda ir: (ir[1].get("position", 0), ir[0]),
    )

    for _, r in sorted_recipients:
        share = (distributable * r["share_bps"]) // 10000
        total_allocated += share
        outputs.append(SplitOutput(
            wallet=r["wallet_address"],
            label=r.get("label", "") or "",
            role=r.get("role", "recipient") or "recipient",
            share_bps=int(r["share_bps"]),
            amount=share,
            position=int(r.get("position", 0)),
        ))

    # 4. Remainder da rounding → va al primary (position più bassa)
    remainder = distributable - total_allocated
    if remainder > 0 and outputs:
        primary = min(outputs, key=lambda o: o.position)
        primary.amount += remainder
        total_allocated += remainder

    # 5. Sanity check — invariante di conservazione
    if total_allocated != distributable:
        raise RuntimeError(
            f"Split math error: allocated {total_allocated} != distributable {distributable}"
        )

    # Invariante aggiuntivo: fee + distributable == input
    if rsend_fee + distributable != input_amount:
        raise RuntimeError(
            f"Conservation error: fee {rsend_fee} + distributable {distributable} "
            f"!= input {input_amount}"
        )

    return SplitPlan(
        contract_id=0,  # Set by caller
        client_id="",   # Set by caller
        input_amount=input_amount,
        rsend_fee=rsend_fee,
        distributable=distributable,
        outputs=outputs,
        remainder=remainder,
        token=token,
        decimals=decimals,
        total_check=total_allocated,
        rsend_fee_bps=rsend_fee_bps,
    )


def format_split_plan(plan: SplitPlan) -> dict:
    """Formatta un SplitPlan per API response / logging.

    Nota: i valori `*_human` usano float solo per DISPLAY.
    La matematica autoritativa è in `*_raw` (stringhe di interi).
    """
    factor = 10 ** plan.decimals
    return {
        "input": {
            "amount_raw": str(plan.input_amount),
            "amount_human": f"{plan.input_amount / factor:.{plan.decimals}f}",
            "token": plan.token,
        },
        "rsend_fee": {
            "amount_raw": str(plan.rsend_fee),
            "amount_human": f"{plan.rsend_fee / factor:.{plan.decimals}f}",
            "bps": plan.rsend_fee_bps,
        },
        "distributable": {
            "amount_raw": str(plan.distributable),
            "amount_human": f"{plan.distributable / factor:.{plan.decimals}f}",
        },
        "recipients": [
            {
                "wallet": o.wallet,
                "label": o.label,
                "role": o.role,
                "share_percent": f"{o.share_bps / 100:.2f}%",
                "share_bps": o.share_bps,
                "amount_raw": str(o.amount),
                "amount_human": f"{o.amount / factor:.{plan.decimals}f}",
                "position": o.position,
            }
            for o in plan.outputs
        ],
        "remainder_raw": str(plan.remainder),
        "check_passed": plan.total_check == plan.distributable,
    }
