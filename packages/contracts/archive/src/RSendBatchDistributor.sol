// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title RSendBatchDistributor
 * @author RSends Team
 * @notice Production batch distributor for RSends payment gateway on Base L2.
 *         Distributes ETH or ERC20 tokens from one sender to up to 500 recipients
 *         in a single transaction, with a configurable fee (basis points) to treasury.
 *
 * @dev Security stack:
 *   - Ownable2Step: prevents accidental ownership transfer
 *   - ReentrancyGuard: protects distribution functions
 *   - Pausable: Guardian can pause, only Owner can unpause
 *   - 24h Timelock: fee changes and guardian changes require proposal + 24h delay
 *   - Daily Spending Caps: on-chain per-token daily limits
 *   - Emergency Withdraw: only Owner, only when paused
 *
 * @dev Optimization notes:
 *   - calldata arrays (no memory copy)
 *   - cached array length in loops
 *   - unchecked i++ in loops
 *   - last recipient gets remainder to prevent dust
 *   - minimized SSTORE via memory caching
 */

import {Ownable2Step, Ownable} from "@openzeppelin/contracts/access/Ownable2Step.sol";
import {ReentrancyGuard}       from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Pausable}              from "@openzeppelin/contracts/utils/Pausable.sol";
import {IERC20}                from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}             from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract RSendBatchDistributor is Ownable2Step, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    // ── Custom errors ──────────────────────────────────────────────────────
    error ZeroAddress();
    error ZeroAmount();
    error ArrayLengthMismatch();
    error TooManyRecipients(uint256 count, uint256 max);
    error InsufficientETH(uint256 required, uint256 sent);
    error ETHTransferFailed(address recipient, uint256 amount);
    error FeeTooHigh(uint256 proposed, uint256 max);
    error DailyCapExceeded(address token, uint256 spent, uint256 cap);
    error NotGuardian();
    error NotOwnerOrGuardian();
    error TimelockNotReady(uint256 readyAt, uint256 currentTime);
    error NoActiveProposal();
    error ProposalAlreadyActive();
    error NotPaused();

    // ── Constants ──────────────────────────────────────────────────────────
    uint256 public constant MAX_RECIPIENTS   = 500;
    uint16  public constant MAX_FEE_BPS      = 1_000;  // 10% hard cap
    uint16  public constant BPS_DENOM        = 10_000;
    uint256 public constant TIMELOCK_DELAY   = 24 hours;

    /// @dev address(0xEEEE...EEEE) sentinel represents native ETH in daily cap mapping
    address public constant ETH_SENTINEL = 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE;

    // ── Storage ────────────────────────────────────────────────────────────

    /// @notice Treasury address that receives fees
    address public treasury;

    /// @notice Fee in basis points (default 50 = 0.5%)
    uint16 public feeBps;

    /// @notice Guardian address (should be a Gnosis Safe 2-of-3).
    ///         Can pause() and cancelProposal(). Cannot unpause or distribute.
    address public guardian;

    // ── Timelock ───────────────────────────────────────────────────────────

    enum ProposalType { NONE, SET_FEE, SET_GUARDIAN }

    struct Proposal {
        ProposalType pType;
        uint256      value;       // feeBps (uint16 stored as uint256) or guardian address (cast)
        uint256      readyAt;     // block.timestamp + TIMELOCK_DELAY
    }

    /// @notice The currently pending timelock proposal (only one at a time)
    Proposal public activeProposal;

    // ── Daily Spending Cap ─────────────────────────────────────────────────

    struct DailySpending {
        uint256 spent;
        uint256 dayStart;
        uint256 cap;
    }

    /// @notice Daily spending caps per token (ETH_SENTINEL for native ETH)
    mapping(address => DailySpending) public dailyCaps;

    // ── Events ─────────────────────────────────────────────────────────────

    /// @notice Emitted after a successful batch distribution
    event BatchDistributed(
        address indexed sender,
        address indexed token,
        uint256 totalAmount,
        uint256 recipientCount,
        uint256 fee
    );

    /// @notice Emitted for each individual transfer within a batch
    event SingleTransfer(address indexed to, uint256 amount, uint256 index);

    /// @notice Emitted when a timelock proposal is created
    event ProposalCreated(ProposalType indexed pType, uint256 value, uint256 readyAt);

    /// @notice Emitted when a timelock proposal is executed
    event ProposalExecuted(ProposalType indexed pType, uint256 value);

    /// @notice Emitted when a timelock proposal is cancelled
    event ProposalCancelled(ProposalType indexed pType);

    /// @notice Emitted when fee basis points change
    event FeeBpsUpdated(uint16 oldFee, uint16 newFee);

    /// @notice Emitted when guardian changes
    event GuardianUpdated(address oldGuardian, address newGuardian);

    /// @notice Emitted when a daily spending cap is set
    event DailyCapSet(address indexed token, uint256 cap);

    /// @notice Emitted on emergency withdrawal
    event EmergencyWithdraw(address indexed token, address indexed to, uint256 amount);

    // ── Modifiers ──────────────────────────────────────────────────────────

    modifier onlyGuardian() {
        if (msg.sender != guardian) revert NotGuardian();
        _;
    }

    // ── Constructor ────────────────────────────────────────────────────────

    /**
     * @param _owner    Contract owner (multi-sig recommended)
     * @param _treasury Treasury address for fee collection
     * @param _guardian Guardian address (Gnosis Safe 2-of-3 recommended)
     * @param _feeBps   Initial fee in basis points (e.g. 50 = 0.5%)
     */
    constructor(
        address _owner,
        address _treasury,
        address _guardian,
        uint16  _feeBps
    ) Ownable(_owner) {
        if (_treasury == address(0)) revert ZeroAddress();
        if (_guardian == address(0)) revert ZeroAddress();
        if (_feeBps > MAX_FEE_BPS)  revert FeeTooHigh(_feeBps, MAX_FEE_BPS);

        treasury = _treasury;
        guardian = _guardian;
        feeBps   = _feeBps;

        emit GuardianUpdated(address(0), _guardian);
        emit FeeBpsUpdated(0, _feeBps);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  DISTRIBUTION — ETH
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @notice Distribute ETH to multiple recipients with fee deduction.
     * @dev    Amounts are pre-calculated off-chain. Last recipient gets remainder
     *         to prevent dust. Fee is calculated on the total msg.value.
     *         Uses low-level call{value:} — NOT transfer (2300 gas limit).
     *
     * @param recipients Array of recipient addresses (max 500)
     * @param amounts    Array of amounts per recipient (must match recipients length)
     */
    function distributeETH(
        address[] calldata recipients,
        uint256[] calldata amounts
    ) external payable nonReentrant whenNotPaused {
        uint256 len = recipients.length;
        if (len == 0)                    revert ZeroAmount();
        if (len != amounts.length)       revert ArrayLengthMismatch();
        if (len > MAX_RECIPIENTS)        revert TooManyRecipients(len, MAX_RECIPIENTS);

        // Calculate fee on total value
        uint256 totalValue = msg.value;
        if (totalValue == 0) revert ZeroAmount();

        uint256 fee = (totalValue * feeBps) / BPS_DENOM;
        uint256 distributable = totalValue - fee;

        // Verify sum of amounts <= distributable
        uint256 sumAmounts;
        for (uint256 i; i < len;) {
            sumAmounts += amounts[i];
            unchecked { ++i; }
        }
        if (sumAmounts > distributable) revert InsufficientETH(sumAmounts, distributable);

        // Daily spending cap check
        _checkAndUpdateDailyCap(ETH_SENTINEL, totalValue);

        // Distribute to recipients
        uint256 totalSent;
        uint256 lastIdx;
        unchecked { lastIdx = len - 1; }

        for (uint256 i; i < len;) {
            address recipient = recipients[i];
            if (recipient == address(0)) revert ZeroAddress();

            uint256 amt;
            if (i == lastIdx) {
                // Last recipient gets remainder to prevent dust
                amt = distributable - totalSent;
            } else {
                amt = amounts[i];
            }

            (bool success,) = recipient.call{value: amt}("");
            if (!success) revert ETHTransferFailed(recipient, amt);

            emit SingleTransfer(recipient, amt, i);
            totalSent += amt;

            unchecked { ++i; }
        }

        // Send fee to treasury
        if (fee > 0) {
            (bool feeSuccess,) = treasury.call{value: fee}("");
            if (!feeSuccess) revert ETHTransferFailed(treasury, fee);
        }

        // Refund any excess ETH (distributable - totalSent would be 0 for last-gets-remainder,
        // but fee rounding could leave wei dust)
        uint256 remaining = address(this).balance;
        if (remaining > 0) {
            (bool refundSuccess,) = msg.sender.call{value: remaining}("");
            if (!refundSuccess) revert ETHTransferFailed(msg.sender, remaining);
        }

        emit BatchDistributed(msg.sender, address(0), totalValue, len, fee);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  DISTRIBUTION — ERC20
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @notice Distribute ERC20 tokens to multiple recipients with fee deduction.
     * @dev    Caller must approve this contract for totalAmount before calling.
     *         Uses SafeERC20 for pull + distribute. Last recipient gets remainder.
     *
     * @param token      ERC20 token to distribute
     * @param recipients Array of recipient addresses (max 500)
     * @param amounts    Array of amounts per recipient
     */
    function distributeERC20(
        IERC20  token,
        address[] calldata recipients,
        uint256[] calldata amounts
    ) external nonReentrant whenNotPaused {
        uint256 len = recipients.length;
        if (len == 0)                    revert ZeroAmount();
        if (len != amounts.length)       revert ArrayLengthMismatch();
        if (len > MAX_RECIPIENTS)        revert TooManyRecipients(len, MAX_RECIPIENTS);
        if (address(token) == address(0)) revert ZeroAddress();

        // Sum total amount needed
        uint256 totalAmount;
        for (uint256 i; i < len;) {
            totalAmount += amounts[i];
            unchecked { ++i; }
        }
        if (totalAmount == 0) revert ZeroAmount();

        // Calculate fee
        uint256 fee = (totalAmount * feeBps) / BPS_DENOM;
        uint256 pullAmount = totalAmount + fee;

        // Daily spending cap check
        _checkAndUpdateDailyCap(address(token), pullAmount);

        // Pull total (amounts + fee) from sender
        token.safeTransferFrom(msg.sender, address(this), pullAmount);

        // Distribute to recipients
        uint256 totalSent;
        uint256 lastIdx;
        unchecked { lastIdx = len - 1; }

        for (uint256 i; i < len;) {
            address recipient = recipients[i];
            if (recipient == address(0)) revert ZeroAddress();

            uint256 amt;
            if (i == lastIdx) {
                // Last recipient gets remainder to prevent dust
                amt = totalAmount - totalSent;
            } else {
                amt = amounts[i];
            }

            token.safeTransfer(recipient, amt);
            emit SingleTransfer(recipient, amt, i);
            totalSent += amt;

            unchecked { ++i; }
        }

        // Send fee to treasury
        if (fee > 0) {
            token.safeTransfer(treasury, fee);
        }

        emit BatchDistributed(msg.sender, address(token), pullAmount, len, fee);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  DAILY SPENDING CAP
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @notice Set the daily spending cap for a token (use ETH_SENTINEL for native ETH).
     * @param token  Token address (or ETH_SENTINEL for ETH)
     * @param cap    Maximum amount that can be distributed in a 24h window (0 = no cap)
     */
    function setDailyCap(address token, uint256 cap) external onlyOwner {
        dailyCaps[token].cap = cap;
        emit DailyCapSet(token, cap);
    }

    /**
     * @dev Check and update daily spending. Reverts if cap would be exceeded.
     *      A cap of 0 means no limit is enforced for that token.
     */
    function _checkAndUpdateDailyCap(address token, uint256 amount) internal {
        DailySpending storage ds = dailyCaps[token];
        uint256 cap = ds.cap;

        // Cap of 0 = unlimited
        if (cap == 0) return;

        uint256 currentDay = block.timestamp / 1 days;

        // Reset if new day
        if (ds.dayStart != currentDay) {
            ds.spent = 0;
            ds.dayStart = currentDay;
        }

        uint256 newSpent = ds.spent + amount;
        if (newSpent > cap) revert DailyCapExceeded(token, newSpent, cap);

        ds.spent = newSpent;
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  TIMELOCK — PROPOSE / EXECUTE / CANCEL
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @notice Propose a new fee (basis points). Subject to 24h timelock.
     * @param newFeeBps New fee in basis points
     */
    function proposeSetFee(uint16 newFeeBps) external onlyOwner {
        if (activeProposal.pType != ProposalType.NONE) revert ProposalAlreadyActive();
        if (newFeeBps > MAX_FEE_BPS) revert FeeTooHigh(newFeeBps, MAX_FEE_BPS);

        uint256 readyAt = block.timestamp + TIMELOCK_DELAY;
        activeProposal = Proposal({
            pType:   ProposalType.SET_FEE,
            value:   uint256(newFeeBps),
            readyAt: readyAt
        });

        emit ProposalCreated(ProposalType.SET_FEE, uint256(newFeeBps), readyAt);
    }

    /**
     * @notice Propose a new guardian address. Subject to 24h timelock.
     * @param newGuardian New guardian address
     */
    function proposeSetGuardian(address newGuardian) external onlyOwner {
        if (activeProposal.pType != ProposalType.NONE) revert ProposalAlreadyActive();
        if (newGuardian == address(0)) revert ZeroAddress();

        uint256 readyAt = block.timestamp + TIMELOCK_DELAY;
        activeProposal = Proposal({
            pType:   ProposalType.SET_GUARDIAN,
            value:   uint256(uint160(newGuardian)),
            readyAt: readyAt
        });

        emit ProposalCreated(ProposalType.SET_GUARDIAN, uint256(uint160(newGuardian)), readyAt);
    }

    /**
     * @notice Execute a matured proposal. Anyone can call after the delay has passed.
     */
    function executeProposal() external {
        Proposal memory p = activeProposal;
        if (p.pType == ProposalType.NONE) revert NoActiveProposal();
        if (block.timestamp < p.readyAt)  revert TimelockNotReady(p.readyAt, block.timestamp);

        // Clear proposal before execution (CEI pattern)
        delete activeProposal;

        if (p.pType == ProposalType.SET_FEE) {
            uint16 oldFee = feeBps;
            uint16 newFee = uint16(p.value);
            feeBps = newFee;
            emit FeeBpsUpdated(oldFee, newFee);
            emit ProposalExecuted(ProposalType.SET_FEE, p.value);
        } else if (p.pType == ProposalType.SET_GUARDIAN) {
            address oldGuardian = guardian;
            address newGuardian = address(uint160(p.value));
            guardian = newGuardian;
            emit GuardianUpdated(oldGuardian, newGuardian);
            emit ProposalExecuted(ProposalType.SET_GUARDIAN, p.value);
        }
    }

    /**
     * @notice Cancel an active proposal. Only guardian or owner can cancel.
     */
    function cancelProposal() external {
        if (msg.sender != guardian && msg.sender != owner()) revert NotOwnerOrGuardian();
        if (activeProposal.pType == ProposalType.NONE) revert NoActiveProposal();

        ProposalType pType = activeProposal.pType;
        delete activeProposal;

        emit ProposalCancelled(pType);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  PAUSE / UNPAUSE
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @notice Pause all distributions. Guardian OR Owner can pause.
     */
    function pause() external {
        if (msg.sender != guardian && msg.sender != owner()) revert NotOwnerOrGuardian();
        _pause();
    }

    /**
     * @notice Unpause distributions. Only Owner can unpause.
     */
    function unpause() external onlyOwner {
        _unpause();
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  EMERGENCY WITHDRAW (only Owner, only when paused)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @notice Emergency withdraw all ETH. Only owner, only when paused.
     * @param to Destination address
     */
    function emergencyWithdrawETH(address payable to) external onlyOwner {
        if (!paused()) revert NotPaused();
        if (to == address(0)) revert ZeroAddress();

        uint256 bal = address(this).balance;
        if (bal == 0) revert ZeroAmount();

        (bool success,) = to.call{value: bal}("");
        if (!success) revert ETHTransferFailed(to, bal);

        emit EmergencyWithdraw(address(0), to, bal);
    }

    /**
     * @notice Emergency withdraw all of an ERC20 token. Only owner, only when paused.
     * @param token ERC20 token to withdraw
     * @param to    Destination address
     */
    function emergencyWithdrawERC20(IERC20 token, address to) external onlyOwner {
        if (!paused()) revert NotPaused();
        if (to == address(0)) revert ZeroAddress();

        uint256 bal = token.balanceOf(address(this));
        if (bal == 0) revert ZeroAmount();

        token.safeTransfer(to, bal);

        emit EmergencyWithdraw(address(token), to, bal);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  OWNER — Direct setters (no timelock)
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @notice Update treasury address. No timelock (Owner-only, immediate).
     * @param newTreasury New treasury address
     */
    function setTreasury(address newTreasury) external onlyOwner {
        if (newTreasury == address(0)) revert ZeroAddress();
        treasury = newTreasury;
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  VIEW HELPERS
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * @notice Calculate fee and net amount for a given gross amount.
     * @param grossAmount Total amount before fee
     * @return net Amount after fee deduction
     * @return fee Fee amount
     */
    function calcSplit(uint256 grossAmount) external view returns (uint256 net, uint256 fee) {
        fee = (grossAmount * feeBps) / BPS_DENOM;
        net = grossAmount - fee;
    }

    /**
     * @notice Get the daily spending info for a token.
     * @param token Token address (use ETH_SENTINEL for ETH)
     * @return spent     Amount spent today
     * @return dayStart  Current day identifier
     * @return cap       Daily cap (0 = unlimited)
     */
    function getDailySpending(address token) external view returns (
        uint256 spent,
        uint256 dayStart,
        uint256 cap
    ) {
        DailySpending storage ds = dailyCaps[token];
        uint256 currentDay = block.timestamp / 1 days;

        // If it's a new day, the effective spent is 0
        if (ds.dayStart != currentDay) {
            return (0, currentDay, ds.cap);
        }
        return (ds.spent, ds.dayStart, ds.cap);
    }

    /// @dev Accept ETH sent directly (e.g. refunds from failed calls during distribution)
    receive() external payable {}
}
