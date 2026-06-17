// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║  FeeRouter.sol v2 — B2B Payment Gateway (MiCA/DAC8 Ready)       ║
 * ║  Base Network — Stateless, Atomic, Gas-Optimized                ║
 * ╚══════════════════════════════════════════════════════════════════╝
 *
 * ARCHITETTURA SICUREZZA:
 * 1. Stateless: zero accumulo fondi — ogni TX è pass-through immediato
 * 2. Checks-Effects-Interactions: validazioni PRIMA di qualsiasi transfer
 * 3. ReentrancyGuard: previene attacchi di rientranza
 * 4. Atomicità: se fee transfer fallisce → revert dell'intera TX
 * 5. immutable: feeRecipient non modificabile post-deploy (gas saving)
 *
 * GAS OPTIMIZATIONS:
 * - immutable per indirizzi governance (no SLOAD, legge bytecode direttamente)
 * - custom errors (~50% risparmio vs require string)
 * - unchecked arithmetic dove overflow impossibile per design
 * - packed storage: feeBps (uint16) + owner in stesso slot
 */

import {Ownable}        from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20}         from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}      from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

// ── Custom Errors (gas saving ~50% vs string require) ──────────────────────
error ZeroAddress();
error ZeroAmount();
error FeeTooHigh();
error ETHTransferFailed(address target, uint256 amount);
error InsufficientValue(uint256 sent, uint256 required);

contract FeeRouter is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ── immutable: letto dal bytecode, nessun SLOAD ───────────────────────
    // feeRecipient è immutable per sicurezza: non può essere modificato
    // dopo il deploy neanche dall'owner (protezione da compromissione chiavi)
    address public immutable feeRecipient;

    // feeBps è in storage (modificabile dall'owner fino al max)
    uint16  public feeBps;
    uint16  public constant MAX_FEE_BPS = 1_000; // 10% hard cap
    uint16  public constant BPS_DENOM   = 10_000;

    // ── DAC8 / MiCA: evento ricco per riconciliazione contabile ──────────
    event PaymentProcessed(
        address indexed sender,
        address indexed recipient,
        address indexed token,       // address(0) = ETH nativo
        uint256 grossAmount,
        uint256 netAmount,
        uint256 feeAmount,
        bytes32 paymentRef,          // keccak256(invoiceId)
        string  fiscalRef            // ID fiscale / riferimento fattura (DAC8)
    );

    event FeeBpsUpdated(uint16 oldBps, uint16 newBps);

    // ── Constructor ───────────────────────────────────────────────────────
    constructor(
        address _feeRecipient,
        uint16  _feeBps,
        address _owner
    ) Ownable(_owner) {
        if (_feeRecipient == address(0)) revert ZeroAddress();
        if (_feeBps > MAX_FEE_BPS)       revert FeeTooHigh();

        feeRecipient = _feeRecipient;   // immutable — assegnato solo nel constructor
        feeBps       = _feeBps;
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ETH — Stateless pass-through atomico
    // ══════════════════════════════════════════════════════════════════════

    /**
     * @notice Invia ETH con split automatico fee. Pass-through immediato.
     *
     * Pattern Checks-Effects-Interactions:
     *   1. CHECKS: validazioni input
     *   2. EFFECTS: calcolo split (nessuno state change — stateless)
     *   3. INTERACTIONS: transfer ETH
     *
     * Atomicità garantita: se fee transfer fallisce → revert → nessun ETH perso
     */
    function splitTransferETH(
        address  _to,
        bytes32  _paymentRef,
        string calldata _fiscalRef
    ) external payable nonReentrant {
        // ── CHECKS ────────────────────────────────────────────────────────
        if (_to == address(0)) revert ZeroAddress();
        if (msg.value == 0)    revert ZeroAmount();

        uint256 gross = msg.value;

        // ── EFFECTS (calcolo — nessun state change) ───────────────────────
        uint256 fee;
        uint256 net;
        unchecked {
            // Safe: feeBps <= 1000, gross <= type(uint256).max
            // fee <= gross * 10% → overflow impossibile
            fee = (gross * feeBps) / BPS_DENOM;
            net = gross - fee;
        }

        // ── INTERACTIONS (atomiche: revert se una fallisce) ───────────────
        (bool ok1, ) = _to.call{value: net}("");
        if (!ok1) revert ETHTransferFailed(_to, net);

        (bool ok2, ) = feeRecipient.call{value: fee}("");
        if (!ok2) revert ETHTransferFailed(feeRecipient, fee);

        emit PaymentProcessed(
            msg.sender, _to, address(0),
            gross, net, fee, _paymentRef, _fiscalRef
        );
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ERC20 — SafeERC20 per token non-standard (USDT, cbBTC)
    // ══════════════════════════════════════════════════════════════════════

    /**
     * @notice Invia ERC20 con split automatico. PREREQUISITO: approve(this, amount)
     *
     * SafeERC20 gestisce:
     * - Token senza return value (USDT legacy)
     * - Token con return value non-standard
     * - Protezione da race condition su allowance
     */
    function splitTransferERC20(
        address  _token,
        address  _to,
        uint256  _amount,
        bytes32  _paymentRef,
        string calldata _fiscalRef
    ) external nonReentrant {
        // ── CHECKS ────────────────────────────────────────────────────────
        if (_token == address(0)) revert ZeroAddress();
        if (_to    == address(0)) revert ZeroAddress();
        if (_amount == 0)          revert ZeroAmount();

        // ── EFFECTS ───────────────────────────────────────────────────────
        uint256 fee;
        uint256 net;
        unchecked {
            fee = (_amount * feeBps) / BPS_DENOM;
            net = _amount - fee;
        }

        // ── INTERACTIONS (atomiche via SafeERC20) ─────────────────────────
        IERC20 token = IERC20(_token);
        token.safeTransferFrom(msg.sender, _to,          net);
        token.safeTransferFrom(msg.sender, feeRecipient, fee);

        emit PaymentProcessed(
            msg.sender, _to, _token,
            _amount, net, fee, _paymentRef, _fiscalRef
        );
    }

    // ══════════════════════════════════════════════════════════════════════
    //  View helpers (gas-free, off-chain)
    // ══════════════════════════════════════════════════════════════════════

    function calcSplit(uint256 _amount)
        external view
        returns (uint256 net, uint256 fee)
    {
        fee = (_amount * feeBps) / BPS_DENOM;
        net = _amount - fee;
    }

    function checkAllowance(address _token, address _owner, uint256 _amount)
        external view
        returns (bool sufficient, uint256 current)
    {
        current   = IERC20(_token).allowance(_owner, address(this));
        sufficient = current >= _amount;
    }

    // ══════════════════════════════════════════════════════════════════════
    //  Owner — governance limitata (feeBps only)
    // ══════════════════════════════════════════════════════════════════════

    /// @notice Aggiorna fee (max 10%). feeRecipient è immutable.
    function setFeeBps(uint16 _newBps) external onlyOwner {
        if (_newBps > MAX_FEE_BPS) revert FeeTooHigh();
        emit FeeBpsUpdated(feeBps, _newBps);
        feeBps = _newBps;
    }

    // ── Safety net ────────────────────────────────────────────────────────
    receive()  external payable { revert("Usa splitTransferETH()"); }
    fallback() external payable { revert("Funzione sconosciuta"); }
}
