// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {IERC20}          from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}       from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

error LengthMismatch();
error BadRecipientCount();
error BpsSumNot10000();
error ZeroRecipient();
error ZeroBps();
error ZeroAmount();
error ZeroToken();
error DuplicateRecipient();
error NoPolicy();
error BelowMinAmount(uint256 amount, uint256 minAmount);

/// RSendsAutoSplit — distribuzione periodica non-custodial del saldo di un
/// wallet merchant dedicato. Il merchant approva UNA volta
/// (token.approve(autoSplit, MAX)) e registra una policy (2..10 destinatari,
/// bps a somma ESATTA 10000, minAmount). executeSplit è permissionless:
/// chiunque (keeper incluso) distribuisce min(balance, allowance) via
/// transferFrom merchant -> recipient[i], tutto-o-niente, e con allowance MAX
/// il wallet chiude a saldo ESATTAMENTE zero. Revoca unilaterale: approve(0).
/// Nessun owner, pause, upgrade, delegatecall o call arbitraria: il contratto
/// non detiene mai saldo e nessun ruolo privilegiato esiste.
///
/// NOTA resto: qui il resto della divisione intera va all'ULTIMO recipient
/// (amount - somma dei floor precedenti), NON al primo come in
/// RSendsSplitRouter/_computeAmounts. Questa matematica NON va replicata via
/// split_math.py — quel modulo rispecchia il SOLO SplitRouter.
contract RSendsAutoSplit is ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 public constant MIN_RECIPIENTS = 2;
    uint256 public constant MAX_RECIPIENTS = 10;
    uint256 public constant BPS_DENOMINATOR = 10_000;

    struct Policy {
        address[] recipients;
        uint16[] bps;
        uint256 minAmount;
    }

    /// L'unica scrittura passa da setPolicy/clearPolicy con chiave
    /// msg.sender: nessuno può toccare la policy di un altro merchant.
    mapping(address merchant => mapping(address token => Policy)) private _policies;

    event PolicySet(
        address indexed merchant, address indexed token,
        address[] recipients, uint16[] bps, uint256 minAmount
    );
    event PolicyCleared(address indexed merchant, address indexed token);
    event SplitExecuted(
        address indexed merchant, address indexed token, address indexed caller,
        uint256 totalAmount, address[] recipients, uint256[] amounts, uint256 blockTimestamp
    );

    /// Registra (o sostituisce integralmente) la policy di msg.sender per
    /// `token`. Valida forma e somma; i duplicati sono rifiutati perché una
    /// leg doppia è quasi certamente un errore di configurazione.
    function setPolicy(
        address token, address[] calldata recipients, uint16[] calldata bps, uint256 minAmount
    ) external {
        if (token == address(0)) revert ZeroToken();
        uint256 n = recipients.length;
        if (n != bps.length) revert LengthMismatch();
        if (n < MIN_RECIPIENTS || n > MAX_RECIPIENTS) revert BadRecipientCount();

        uint256 bpsSum;
        for (uint256 i; i < n; ++i) {
            address to = recipients[i];
            if (to == address(0)) revert ZeroRecipient();
            if (bps[i] == 0) revert ZeroBps();
            bpsSum += bps[i];
            for (uint256 j = i + 1; j < n; ++j) {
                if (recipients[j] == to) revert DuplicateRecipient();
            }
        }
        if (bpsSum != BPS_DENOMINATOR) revert BpsSumNot10000();

        Policy storage p = _policies[msg.sender][token];
        p.recipients = recipients; // calldata->storage copy replaces, shrink included
        p.bps = bps;
        p.minAmount = minAmount;

        emit PolicySet(msg.sender, token, recipients, bps, minAmount);
    }

    /// Rimuove la policy di msg.sender per `token`. Idempotente.
    function clearPolicy(address token) external {
        delete _policies[msg.sender][token];
        emit PolicyCleared(msg.sender, token);
    }

    /// Permissionless: distribuisce min(balance, allowance) del merchant
    /// secondo la sua policy. Ogni leg è un safeTransferFrom diretto
    /// merchant -> recipient: se UNA fallisce (es. blacklist USDC), l'intera
    /// esecuzione reverte — mai una distribuzione parziale.
    function executeSplit(address merchant, address token) external nonReentrant {
        Policy storage p = _policies[merchant][token];
        (uint256 total, uint256[] memory amounts) = _plan(p, merchant, token);

        uint256 n = p.recipients.length;
        address[] memory plain = new address[](n); // per l'evento, snapshot della policy
        for (uint256 i; i < n; ++i) {
            address to = p.recipients[i];
            plain[i] = to;
            IERC20(token).safeTransferFrom(merchant, to, amounts[i]);
        }
        emit SplitExecuted(merchant, token, msg.sender, total, plain, amounts, block.timestamp);
    }

    function getPolicy(address merchant, address token)
        external view
        returns (address[] memory recipients, uint16[] memory bps, uint256 minAmount)
    {
        Policy storage p = _policies[merchant][token];
        return (p.recipients, p.bps, p.minAmount);
    }

    /// Pre-flight per il keeper: stessi guard e stessa matematica di
    /// executeSplit (reverte NoPolicy/ZeroAmount/BelowMinAmount), così una
    /// eth_call che passa qui è una executeSplit che non brucia gas invano.
    function previewSplit(address merchant, address token)
        external view
        returns (uint256 total, uint256[] memory amounts)
    {
        return _plan(_policies[merchant][token], merchant, token);
    }

    /// Guard comuni + calcolo importi: floor division per leg, resto
    /// all'ULTIMA — così sum(amounts) == total e il wallet chiude a zero.
    function _plan(Policy storage p, address merchant, address token)
        private view
        returns (uint256 total, uint256[] memory amounts)
    {
        uint256 n = p.recipients.length;
        if (n == 0) revert NoPolicy();

        uint256 balance = IERC20(token).balanceOf(merchant);
        uint256 allowance = IERC20(token).allowance(merchant, address(this));
        total = balance < allowance ? balance : allowance;
        if (total == 0) revert ZeroAmount();
        if (total < p.minAmount) revert BelowMinAmount(total, p.minAmount);

        amounts = new uint256[](n);
        uint256 allocated;
        for (uint256 i; i < n - 1; ++i) {
            uint256 amt = (total * p.bps[i]) / BPS_DENOMINATOR;
            amounts[i] = amt;
            allocated += amt;
        }
        amounts[n - 1] = total - allocated;
    }
}
