// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20}          from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}       from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {IERC20Permit}    from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Permit.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

error ZeroMerchant();
error ZeroAmount();
error ZeroToken();
error WrongNativeValue();
error NativeTransferFailed();

/// RSendsRouterV2 — router di pagamento singolo-merchant SENZA fee e SENZA owner.
///
/// Un pagamento è UN solo trasferimento, payer -> merchant, per esattamente
/// `amount`: nessuna fee leg, nessuno stato fee, nessun evento fee
/// (monetizzazione = subscription off-chain). Nessun ruolo privilegiato
/// esiste: niente owner, pause o whitelist — non c'è chiave da proteggere né
/// superficie admin da difendere. Il contratto non detiene mai saldo (nessun
/// receive/fallback; il path native pretende msg.value ESATTO e inoltra
/// nello stesso call): non-custodial per costruzione, non per policy.
///
/// Nessuna whitelist on-chain significa che il gate sul token è SOLO
/// off-chain (validazione alla creazione dell'intent + match evento<->intent
/// nell'indexer) — scelta documentata in AUDIT_HANDOFF_ROUTERV2.md. Deployato
/// ACCANTO a RSendsRouter (testnet, immutato) e RSendsSplitRouter (stesso
/// modello ownerless/feeless, multi-recipient).
contract RSendsRouterV2 is ReentrancyGuard {
    using SafeERC20 for IERC20;

    /// Stessa topologia indicizzata del PaymentMade v1 MENO la parola fee:
    /// l'indexer riconosce entrambe le shape per topic0 (dual decode).
    event PaymentMade(
        bytes32 indexed invoiceId, address indexed merchant, address indexed payer,
        address token, uint256 amount, uint256 blockTimestamp
    );

    /// Payer deve aver approvato ESATTAMENTE amount. Merchant riceve amount
    /// (token FoT esclusi: nessun gate on-chain, vedi header).
    function pay(bytes32 invoiceId, address merchant, address token, uint256 amount)
        external nonReentrant
    {
        if (merchant == address(0)) revert ZeroMerchant();
        if (amount == 0) revert ZeroAmount();
        if (token == address(0)) revert ZeroToken();
        IERC20(token).safeTransferFrom(msg.sender, merchant, amount);
        emit PaymentMade(invoiceId, merchant, msg.sender, token, amount, block.timestamp);
    }

    /// Come pay() con permit EIP-2612 su ESATTAMENTE amount (nessun termine
    /// fee). Permit catturato (try/catch, front-run resilient), fallback
    /// all'allowance esistente — stesso pattern degli altri router.
    function payWithPermit(
        bytes32 invoiceId, address merchant, address token, uint256 amount,
        uint256 deadline, uint8 v, bytes32 r, bytes32 s
    ) external nonReentrant {
        if (merchant == address(0)) revert ZeroMerchant();
        if (amount == 0) revert ZeroAmount();
        if (token == address(0)) revert ZeroToken();
        try IERC20Permit(token).permit(msg.sender, address(this), amount, deadline, v, r, s) {} catch {}
        IERC20(token).safeTransferFrom(msg.sender, merchant, amount);
        emit PaymentMade(invoiceId, merchant, msg.sender, token, amount, block.timestamp);
    }

    /// Native ETH. msg.value deve essere ESATTAMENTE amount; inoltro diretto
    /// nello stesso call — il router non trattiene mai un wei.
    function payNative(bytes32 invoiceId, address payable merchant, uint256 amount)
        external payable nonReentrant
    {
        if (merchant == address(0)) revert ZeroMerchant();
        if (amount == 0) revert ZeroAmount();
        if (msg.value != amount) revert WrongNativeValue();
        (bool ok, ) = merchant.call{value: amount}("");
        if (!ok) revert NativeTransferFailed();
        emit PaymentMade(invoiceId, merchant, msg.sender, address(0), amount, block.timestamp);
    }
}
