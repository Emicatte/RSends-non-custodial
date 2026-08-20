// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {IERC20}          from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}       from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {IERC20Permit}    from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Permit.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Pausable}        from "@openzeppelin/contracts/utils/Pausable.sol";
import {Ownable}         from "@openzeppelin/contracts/access/Ownable.sol";
import {Ownable2Step}    from "@openzeppelin/contracts/access/Ownable2Step.sol";

error ZeroMerchant();
error ZeroAmount();
error ZeroAddress();
error UnsupportedToken(address token);
error NativeTransferFailed();
error FeeTransferFailed();
error WrongNativeValue();
error FeeTooHigh();

/// RSendsRouter — non-custodial flat-fee router con fee on-chain.
/// Fondi: payer -> merchant diretto; fee: payer -> feeCollector diretto.
/// Il router non detiene mai saldo. L'owner configura SOLO la fee, il
/// destinatario fee e la whitelist token (`enabled`): non può MAI
/// muovere/trattenere/redirezionare i fondi del merchant.
/// fee = baseFee + (amount >= threshold ? surcharge : 0) → cappata da `maxFee`.
/// Un token è pagabile SOLO se `feeConfig[token].enabled` (la config È la
/// whitelist on-chain). Il native (address(0)) è abilitato e feeless di default.
contract RSendsRouter is Ownable2Step, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct FeeConfig { uint256 baseFee; uint256 threshold; uint256 surcharge; bool enabled; }
    mapping(address token => FeeConfig) public feeConfig; // token==address(0) => native
    address public feeCollector;                          // riceve SOLO fee

    event PaymentMade(
        bytes32 indexed invoiceId, address indexed merchant, address indexed payer,
        address token, uint256 amount, uint256 fee, uint256 blockTimestamp
    );
    event FeeConfigSet(address indexed token, uint256 baseFee, uint256 threshold, uint256 surcharge, bool enabled);
    event FeeCollectorSet(address indexed feeCollector);

    constructor(address initialOwner, address initialFeeCollector) Ownable(initialOwner) {
        if (initialFeeCollector == address(0)) revert ZeroAddress();
        feeCollector = initialFeeCollector;
        emit FeeCollectorSet(initialFeeCollector);
        // Native asset: abilitato e feeless di default (gli stablecoin sono il core;
        // una fee EUR-stabile su ETH richiederebbe un oracle, qui assente).
        feeConfig[address(0)] = FeeConfig(0, 0, 0, true);
        emit FeeConfigSet(address(0), 0, 0, 0, true);
    }

    /// Fee per token+amount. Il frontend la usa per calcolare l'approve totale.
    /// Pura quote (NON gated): la whitelist è applicata nei path di pagamento.
    function quoteFee(address token, uint256 amount) public view returns (uint256 fee) {
        FeeConfig memory c = feeConfig[token];
        fee = c.baseFee;
        if (c.threshold != 0 && amount >= c.threshold) fee += c.surcharge;
    }

    /// Payer deve aver approvato (amount + quoteFee). Merchant riceve esatto amount.
    /// `maxFee` è il tetto lato payer: se quoteFee > maxFee la tx reverte (protegge
    /// da qualunque cambio di fee / compromissione chiave fra quote e firma).
    function pay(bytes32 invoiceId, address merchant, address token, uint256 amount, uint256 maxFee)
        external nonReentrant whenNotPaused
    {
        if (merchant == address(0)) revert ZeroMerchant();
        if (amount == 0) revert ZeroAmount();
        if (token == address(0) || !feeConfig[token].enabled) revert UnsupportedToken(token);
        uint256 fee = quoteFee(token, amount);
        if (fee > maxFee) revert FeeTooHigh();
        IERC20(token).safeTransferFrom(msg.sender, merchant, amount);
        if (fee != 0) IERC20(token).safeTransferFrom(msg.sender, feeCollector, fee);
        emit PaymentMade(invoiceId, merchant, msg.sender, token, amount, fee, block.timestamp);
    }

    /// Come pay() con permit EIP-2612 su (amount + fee). USDT/DAI non hanno EIP-2612
    /// standard → permit catturato (try/catch, front-run resilient), fallback
    /// all'allowance esistente.
    function payWithPermit(
        bytes32 invoiceId, address merchant, address token, uint256 amount, uint256 maxFee,
        uint256 deadline, uint8 v, bytes32 r, bytes32 s
    ) external nonReentrant whenNotPaused {
        if (merchant == address(0)) revert ZeroMerchant();
        if (amount == 0) revert ZeroAmount();
        if (token == address(0) || !feeConfig[token].enabled) revert UnsupportedToken(token);
        uint256 fee = quoteFee(token, amount);
        if (fee > maxFee) revert FeeTooHigh();
        try IERC20Permit(token).permit(msg.sender, address(this), amount + fee, deadline, v, r, s) {} catch {}
        IERC20(token).safeTransferFrom(msg.sender, merchant, amount);
        if (fee != 0) IERC20(token).safeTransferFrom(msg.sender, feeCollector, fee);
        emit PaymentMade(invoiceId, merchant, msg.sender, token, amount, fee, block.timestamp);
    }

    /// Native ETH. msg.value deve essere esattamente amount + quoteFee(0, amount).
    /// Default: native feeless (una fee EUR-stabile su ETH servirebbe un oracle).
    function payNative(bytes32 invoiceId, address payable merchant, uint256 amount, uint256 maxFee)
        external payable nonReentrant whenNotPaused
    {
        if (merchant == address(0)) revert ZeroMerchant();
        if (amount == 0) revert ZeroAmount();
        if (!feeConfig[address(0)].enabled) revert UnsupportedToken(address(0));
        uint256 fee = quoteFee(address(0), amount);
        if (fee > maxFee) revert FeeTooHigh();
        if (msg.value != amount + fee) revert WrongNativeValue();
        (bool okM, ) = merchant.call{value: amount}("");
        if (!okM) revert NativeTransferFailed();
        if (fee != 0) { (bool okF, ) = payable(feeCollector).call{value: fee}(""); if (!okF) revert FeeTransferFailed(); }
        emit PaymentMade(invoiceId, merchant, msg.sender, address(0), amount, fee, block.timestamp);
    }

    // ── Owner config: NON può muovere/trattenere fondi utente ──
    function setFeeConfig(address token, uint256 baseFee, uint256 threshold, uint256 surcharge, bool enabled)
        external onlyOwner
    {
        feeConfig[token] = FeeConfig(baseFee, threshold, surcharge, enabled);
        emit FeeConfigSet(token, baseFee, threshold, surcharge, enabled);
    }
    function setFeeCollector(address newFeeCollector) external onlyOwner {
        if (newFeeCollector == address(0)) revert ZeroAddress();
        feeCollector = newFeeCollector;
        emit FeeCollectorSet(newFeeCollector);
    }

    function pause() external onlyOwner { _pause(); }
    function unpause() external onlyOwner { _unpause(); }
}
