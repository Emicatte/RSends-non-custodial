// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {IERC20}          from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}       from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {IERC20Permit}    from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Permit.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

error LengthMismatch();
error BadRecipientCount();
error BpsSumNot10000();
error ZeroRecipient();
error ZeroBps();
error ZeroAmount();
error ZeroToken();
error WrongNativeValue();
error NativeTransferFailed();

/// RSendsSplitRouter — split non-custodial SENZA fee e SENZA owner.
/// Una transazione del payer distribuisce il principal a N destinatari per
/// basis points (somma ESATTA == 10000, altrimenti revert): tutto-o-niente,
/// payer -> recipient[i] diretto. Il contratto non detiene mai saldo, non ha
/// fee on-chain (monetizzazione = subscription off-chain), non ha owner, pause
/// o whitelist: nessun ruolo privilegiato esiste. Deployato ACCANTO a
/// RSendsRouter (che resta immutato, singolo merchant + flat fee).
/// Il resto della divisione intera va a recipients[0] (il "primary"):
/// amounts[i] = totalAmount * sharesBps[i] / 10000, conservazione garantita
/// (somma trasferita == totalAmount, mai dust al router).
contract RSendsSplitRouter is ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 public constant MAX_RECIPIENTS = 20;
    uint256 public constant BPS_DENOMINATOR = 10_000;

    /// Un SOLO evento aggregato per pagamento (token == address(0) per il
    /// native): l'indexer valida l'intero vettore recipients/amounts contro
    /// l'intent e scrive UNA settlement row — l'atomicità è strutturale.
    event SplitPaymentMade(
        bytes32 indexed invoiceId, address indexed payer,
        address token, uint256 totalAmount,
        address[] recipients, uint256[] amounts, uint256 blockTimestamp
    );

    /// Payer deve aver approvato ESATTAMENTE totalAmount. Ogni leg è un
    /// safeTransferFrom diretto payer -> recipient: se UNO fallisce, l'intera
    /// split reverte (mai settlement parziale).
    function paySplit(
        bytes32 invoiceId, address token, uint256 totalAmount,
        address[] calldata recipients, uint16[] calldata sharesBps
    ) external nonReentrant {
        _paySplitERC20(invoiceId, token, totalAmount, recipients, sharesBps);
    }

    /// Come paySplit() con permit EIP-2612 su totalAmount. Permit catturato
    /// (try/catch, front-run resilient), fallback all'allowance esistente —
    /// stesso pattern di RSendsRouter.payWithPermit.
    function paySplitWithPermit(
        bytes32 invoiceId, address token, uint256 totalAmount,
        address[] calldata recipients, uint16[] calldata sharesBps,
        uint256 deadline, uint8 v, bytes32 r, bytes32 s
    ) external nonReentrant {
        if (token == address(0)) revert ZeroToken();
        try IERC20Permit(token).permit(msg.sender, address(this), totalAmount, deadline, v, r, s) {} catch {}
        _paySplitERC20(invoiceId, token, totalAmount, recipients, sharesBps);
    }

    /// Native ETH. msg.value deve essere esattamente totalAmount; ogni leg è
    /// un .call{value} diretto — un destinatario che rifiuta fa revertire
    /// l'intera split.
    function paySplitNative(
        bytes32 invoiceId, uint256 totalAmount,
        address payable[] calldata recipients, uint16[] calldata sharesBps
    ) external payable nonReentrant {
        uint256[] memory amounts = _computeAmounts(totalAmount, recipients.length, sharesBps);
        if (msg.value != totalAmount) revert WrongNativeValue();

        uint256 n = recipients.length;
        address[] memory plain = new address[](n); // per l'evento (address[], non payable)
        for (uint256 i; i < n; ++i) {
            address payable to = recipients[i];
            if (to == address(0)) revert ZeroRecipient();
            plain[i] = to;
            (bool ok, ) = to.call{value: amounts[i]}("");
            if (!ok) revert NativeTransferFailed();
        }
        emit SplitPaymentMade(invoiceId, msg.sender, address(0), totalAmount, plain, amounts, block.timestamp);
    }

    // ── interni ──────────────────────────────────────────────

    function _paySplitERC20(
        bytes32 invoiceId, address token, uint256 totalAmount,
        address[] calldata recipients, uint16[] calldata sharesBps
    ) private {
        if (token == address(0)) revert ZeroToken();
        uint256[] memory amounts = _computeAmounts(totalAmount, recipients.length, sharesBps);

        uint256 n = recipients.length;
        for (uint256 i; i < n; ++i) {
            address to = recipients[i];
            if (to == address(0)) revert ZeroRecipient();
            IERC20(token).safeTransferFrom(msg.sender, to, amounts[i]);
        }
        emit SplitPaymentMade(invoiceId, msg.sender, token, totalAmount, recipients, amounts, block.timestamp);
    }

    /// Valida la forma (lunghezze, 2..20, bps > 0, somma ESATTA 10000) e
    /// calcola gli importi: floor division per leg, resto a amounts[0].
    /// Il backend replica ESATTAMENTE questa matematica (split_math) — non
    /// cambiarla senza cambiare entrambi.
    function _computeAmounts(uint256 totalAmount, uint256 nRecipients, uint16[] calldata sharesBps)
        private pure returns (uint256[] memory amounts)
    {
        if (totalAmount == 0) revert ZeroAmount();
        if (nRecipients != sharesBps.length) revert LengthMismatch();
        if (nRecipients < 2 || nRecipients > MAX_RECIPIENTS) revert BadRecipientCount();

        amounts = new uint256[](nRecipients);
        uint256 bpsSum;
        uint256 allocated;
        for (uint256 i; i < nRecipients; ++i) {
            uint256 bps = sharesBps[i];
            if (bps == 0) revert ZeroBps();
            bpsSum += bps;
            uint256 amt = (totalAmount * bps) / BPS_DENOMINATOR;
            amounts[i] = amt;
            allocated += amt;
        }
        if (bpsSum != BPS_DENOMINATOR) revert BpsSumNot10000();
        amounts[0] += totalAmount - allocated; // resto → primary, conservazione esatta
    }
}
