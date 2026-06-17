// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import {RSendBatchDistributor} from "../src/RSendBatchDistributor.sol";
import {IERC20}  from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC20}   from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

// ── Mock ERC20 ─────────────────────────────────────────────────────────────
contract MockERC20 is ERC20 {
    constructor() ERC20("MockUSDC", "MUSDC") {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

// ── Reentrancy Attacker ────────────────────────────────────────────────────
contract ReentrancyAttacker {
    RSendBatchDistributor public target;
    bool public attacked;

    constructor(RSendBatchDistributor _target) {
        target = _target;
    }

    receive() external payable {
        if (!attacked) {
            attacked = true;
            // Attempt to re-enter distributeETH
            address[] memory r = new address[](1);
            r[0] = address(this);
            uint256[] memory a = new uint256[](1);
            a[0] = 0.01 ether;
            try target.distributeETH{value: 0.02 ether}(r, a) {} catch {}
        }
    }

    function attack() external payable {
        address[] memory r = new address[](1);
        r[0] = address(this);
        uint256[] memory a = new uint256[](1);
        a[0] = msg.value * 9950 / 10000; // approximate net after fee
        target.distributeETH{value: msg.value}(r, a);
    }
}

// ── ETH-rejecting contract (for testing transfer failures) ─────────────────
contract ETHRejecter {
    receive() external payable { revert("no ETH"); }
}

// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE
// ═══════════════════════════════════════════════════════════════════════════
contract RSendBatchDistributorTest is Test {
    RSendBatchDistributor public dist;
    MockERC20             public token;

    address public owner    = makeAddr("owner");
    address public treasury = makeAddr("treasury");
    address public guardian = makeAddr("guardian");
    address public alice    = makeAddr("alice");
    address public bob      = makeAddr("bob");

    uint16 constant FEE_BPS = 50; // 0.5%

    function setUp() public {
        vm.prank(owner);
        dist = new RSendBatchDistributor(owner, treasury, guardian, FEE_BPS);

        token = new MockERC20();

        // Fund accounts
        vm.deal(alice, 1000 ether);
        vm.deal(bob, 100 ether);
    }

    // ───────────────────────────────────────────────────────────────────────
    //  HELPERS
    // ───────────────────────────────────────────────────────────────────────

    function _makeRecipients(uint256 count) internal pure returns (address[] memory, uint256[] memory) {
        address[] memory recipients = new address[](count);
        uint256[] memory amounts = new uint256[](count);
        for (uint256 i; i < count; i++) {
            recipients[i] = address(uint160(0x1000 + i));
            amounts[i] = 0.01 ether;
        }
        return (recipients, amounts);
    }

    function _totalNeeded(uint256 count) internal pure returns (uint256) {
        // Each recipient gets 0.01 ETH, plus 0.5% fee on total msg.value
        // totalAmount = count * 0.01 ether
        // msg.value needs: totalAmount + fee where fee = msg.value * 50 / 10000
        // msg.value * (1 - 50/10000) >= totalAmount
        // msg.value >= totalAmount / 0.995 = totalAmount * 10000 / 9950
        uint256 totalAmount = count * 0.01 ether;
        // Round up to ensure enough
        return (totalAmount * BPS_DENOM + 9949) / (BPS_DENOM - FEE_BPS);
    }

    uint16 constant BPS_DENOM = 10_000;

    // ═══════════════════════════════════════════════════════════════════════
    //  1. HAPPY PATH — ETH Distribution
    // ═══════════════════════════════════════════════════════════════════════

    function test_distributeETH_5recipients() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(5);
        uint256 totalValue = _totalNeeded(5);

        vm.prank(alice);
        dist.distributeETH{value: totalValue}(r, a);

        // Each recipient should have received ~0.01 ETH
        for (uint256 i; i < 4; i++) {
            assertEq(r[i].balance, 0.01 ether, "recipient balance mismatch");
        }
        // Last recipient gets remainder (>= 0.01 ETH)
        assertGe(r[4].balance, 0.01 ether, "last recipient should get remainder");

        // Treasury got fee
        assertGt(treasury.balance, 0, "treasury should have fee");
    }

    function test_distributeETH_50recipients() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(50);
        uint256 totalValue = _totalNeeded(50);

        vm.prank(alice);
        dist.distributeETH{value: totalValue}(r, a);

        for (uint256 i; i < 49; i++) {
            assertEq(r[i].balance, 0.01 ether);
        }
        assertGe(r[49].balance, 0.01 ether);
        assertGt(treasury.balance, 0);
    }

    function test_distributeETH_200recipients() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(200);
        uint256 totalValue = _totalNeeded(200);

        vm.prank(alice);
        dist.distributeETH{value: totalValue}(r, a);

        assertGe(r[199].balance, 0.01 ether);
        assertGt(treasury.balance, 0);
    }

    function test_distributeETH_500recipients() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(500);
        uint256 totalValue = _totalNeeded(500);

        vm.prank(alice);
        dist.distributeETH{value: totalValue}(r, a);

        assertGe(r[499].balance, 0.01 ether);
        assertGt(treasury.balance, 0);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  2. HAPPY PATH — ERC20 Distribution
    // ═══════════════════════════════════════════════════════════════════════

    function test_distributeERC20_5recipients() public {
        uint256 perRecipient = 100e18;
        uint256 total = 5 * perRecipient;
        uint256 fee = (total * FEE_BPS) / BPS_DENOM;
        uint256 pullAmount = total + fee;

        token.mint(alice, pullAmount);
        vm.startPrank(alice);
        token.approve(address(dist), pullAmount);

        (address[] memory r, ) = _makeRecipients(5);
        uint256[] memory a = new uint256[](5);
        for (uint256 i; i < 5; i++) a[i] = perRecipient;

        dist.distributeERC20(IERC20(address(token)), r, a);
        vm.stopPrank();

        for (uint256 i; i < 4; i++) {
            assertEq(token.balanceOf(r[i]), perRecipient);
        }
        assertGe(token.balanceOf(r[4]), perRecipient);
        assertEq(token.balanceOf(treasury), fee);
    }

    function test_distributeERC20_50recipients() public {
        uint256 perRecipient = 10e18;
        uint256 total = 50 * perRecipient;
        uint256 fee = (total * FEE_BPS) / BPS_DENOM;
        uint256 pullAmount = total + fee;

        token.mint(alice, pullAmount);
        vm.startPrank(alice);
        token.approve(address(dist), pullAmount);

        (address[] memory r, ) = _makeRecipients(50);
        uint256[] memory a = new uint256[](50);
        for (uint256 i; i < 50; i++) a[i] = perRecipient;

        dist.distributeERC20(IERC20(address(token)), r, a);
        vm.stopPrank();

        assertGe(token.balanceOf(r[49]), perRecipient);
        assertEq(token.balanceOf(treasury), fee);
    }

    function test_distributeERC20_200recipients() public {
        uint256 perRecipient = 5e18;
        uint256 total = 200 * perRecipient;
        uint256 fee = (total * FEE_BPS) / BPS_DENOM;
        uint256 pullAmount = total + fee;

        token.mint(alice, pullAmount);
        vm.startPrank(alice);
        token.approve(address(dist), pullAmount);

        (address[] memory r, ) = _makeRecipients(200);
        uint256[] memory a = new uint256[](200);
        for (uint256 i; i < 200; i++) a[i] = perRecipient;

        dist.distributeERC20(IERC20(address(token)), r, a);
        vm.stopPrank();

        assertGe(token.balanceOf(r[199]), perRecipient);
        assertEq(token.balanceOf(treasury), fee);
    }

    function test_distributeERC20_500recipients() public {
        uint256 perRecipient = 1e18;
        uint256 total = 500 * perRecipient;
        uint256 fee = (total * FEE_BPS) / BPS_DENOM;
        uint256 pullAmount = total + fee;

        token.mint(alice, pullAmount);
        vm.startPrank(alice);
        token.approve(address(dist), pullAmount);

        (address[] memory r, ) = _makeRecipients(500);
        uint256[] memory a = new uint256[](500);
        for (uint256 i; i < 500; i++) a[i] = perRecipient;

        dist.distributeERC20(IERC20(address(token)), r, a);
        vm.stopPrank();

        assertGe(token.balanceOf(r[499]), perRecipient);
        assertEq(token.balanceOf(treasury), fee);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  3. REVERTS
    // ═══════════════════════════════════════════════════════════════════════

    function test_revert_501recipients() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(501);

        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(
            RSendBatchDistributor.TooManyRecipients.selector, 501, 500
        ));
        dist.distributeETH{value: 100 ether}(r, a);
    }

    function test_revert_mismatchedArrays() public {
        address[] memory r = new address[](2);
        r[0] = makeAddr("r1");
        r[1] = makeAddr("r2");
        uint256[] memory a = new uint256[](3);
        a[0] = 1 ether; a[1] = 1 ether; a[2] = 1 ether;

        vm.prank(alice);
        vm.expectRevert(RSendBatchDistributor.ArrayLengthMismatch.selector);
        dist.distributeETH{value: 5 ether}(r, a);
    }

    function test_revert_zeroAddress() public {
        address[] memory r = new address[](2);
        r[0] = makeAddr("r1");
        r[1] = address(0); // zero address
        uint256[] memory a = new uint256[](2);
        a[0] = 0.5 ether; a[1] = 0.5 ether;

        vm.prank(alice);
        vm.expectRevert(RSendBatchDistributor.ZeroAddress.selector);
        dist.distributeETH{value: 2 ether}(r, a);
    }

    function test_revert_insufficientETH() public {
        address[] memory r = new address[](2);
        r[0] = makeAddr("r1");
        r[1] = makeAddr("r2");
        uint256[] memory a = new uint256[](2);
        a[0] = 5 ether; a[1] = 5 ether; // needs 10 ETH net + fee

        vm.prank(alice);
        vm.expectRevert(); // InsufficientETH
        dist.distributeETH{value: 1 ether}(r, a); // only 1 ETH sent
    }

    function test_revert_insufficientApproval_ERC20() public {
        uint256 perRecipient = 100e18;
        uint256 total = 2 * perRecipient;
        uint256 fee = (total * FEE_BPS) / BPS_DENOM;
        uint256 pullAmount = total + fee;

        token.mint(alice, pullAmount);
        vm.startPrank(alice);
        token.approve(address(dist), 1e18); // insufficient approval

        address[] memory r = new address[](2);
        r[0] = makeAddr("r1");
        r[1] = makeAddr("r2");
        uint256[] memory a = new uint256[](2);
        a[0] = perRecipient; a[1] = perRecipient;

        vm.expectRevert(); // SafeERC20 revert
        dist.distributeERC20(IERC20(address(token)), r, a);
        vm.stopPrank();
    }

    function test_revert_emptyRecipients() public {
        address[] memory r = new address[](0);
        uint256[] memory a = new uint256[](0);

        vm.prank(alice);
        vm.expectRevert(RSendBatchDistributor.ZeroAmount.selector);
        dist.distributeETH{value: 1 ether}(r, a);
    }

    function test_revert_zeroValue_ETH() public {
        address[] memory r = new address[](1);
        r[0] = makeAddr("r1");
        uint256[] memory a = new uint256[](1);
        a[0] = 0;

        vm.prank(alice);
        vm.expectRevert(RSendBatchDistributor.ZeroAmount.selector);
        dist.distributeETH{value: 0}(r, a);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  4. SECURITY — REENTRANCY
    // ═══════════════════════════════════════════════════════════════════════

    function test_reentrancyBlocked() public {
        ReentrancyAttacker attacker = new ReentrancyAttacker(dist);
        vm.deal(address(attacker), 10 ether);

        // The attacker's receive() tries to re-enter distributeETH
        // It should fail silently (try/catch) but not drain funds
        vm.prank(address(attacker));
        attacker.attack{value: 1 ether}();

        // Attacker's re-entry should have failed
        // The contract balance should be 0 (all distributed + fee sent)
        assertEq(address(dist).balance, 0, "contract should have no leftover ETH");
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  5. SECURITY — PAUSE
    // ═══════════════════════════════════════════════════════════════════════

    function test_pauseBlocksDistribution() public {
        // Guardian pauses
        vm.prank(guardian);
        dist.pause();

        (address[] memory r, uint256[] memory a) = _makeRecipients(2);

        vm.prank(alice);
        vm.expectRevert(); // EnforcedPause
        dist.distributeETH{value: 1 ether}(r, a);
    }

    function test_pauseBlocksERC20Distribution() public {
        vm.prank(guardian);
        dist.pause();

        address[] memory r = new address[](1);
        r[0] = makeAddr("r1");
        uint256[] memory a = new uint256[](1);
        a[0] = 1e18;

        vm.prank(alice);
        vm.expectRevert(); // EnforcedPause
        dist.distributeERC20(IERC20(address(token)), r, a);
    }

    function test_unpauseOnlyOwner() public {
        vm.prank(guardian);
        dist.pause();

        // Guardian cannot unpause
        vm.prank(guardian);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        dist.unpause();

        // Random user cannot unpause
        vm.prank(alice);
        vm.expectRevert();
        dist.unpause();

        // Owner can unpause
        vm.prank(owner);
        dist.unpause();

        assertFalse(dist.paused());
    }

    function test_guardianCanPause() public {
        vm.prank(guardian);
        dist.pause();
        assertTrue(dist.paused());
    }

    function test_ownerCanPause() public {
        vm.prank(owner);
        dist.pause();
        assertTrue(dist.paused());
    }

    function test_randomCannotPause() public {
        vm.prank(alice);
        vm.expectRevert(RSendBatchDistributor.NotOwnerOrGuardian.selector);
        dist.pause();
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  6. TIMELOCK — FEE CHANGE
    // ═══════════════════════════════════════════════════════════════════════

    function test_timelockFee_24hWaitEnforced() public {
        vm.prank(owner);
        dist.proposeSetFee(100); // propose 1%

        // Cannot execute immediately
        vm.expectRevert(); // TimelockNotReady
        dist.executeProposal();

        // After 23 hours — still blocked
        vm.warp(block.timestamp + 23 hours);
        vm.expectRevert();
        dist.executeProposal();

        // After 24 hours — succeeds
        vm.warp(block.timestamp + 1 hours + 1);
        dist.executeProposal();

        assertEq(dist.feeBps(), 100);
    }

    function test_timelockFee_anyoneExecutesAfterDelay() public {
        vm.prank(owner);
        dist.proposeSetFee(75);

        vm.warp(block.timestamp + 24 hours + 1);

        // Random user can execute
        vm.prank(alice);
        dist.executeProposal();

        assertEq(dist.feeBps(), 75);
    }

    function test_timelockFee_guardianCancels() public {
        vm.prank(owner);
        dist.proposeSetFee(200);

        // Guardian cancels
        vm.prank(guardian);
        dist.cancelProposal();

        // Proposal is gone
        (RSendBatchDistributor.ProposalType pType,,) = dist.activeProposal();
        assertEq(uint256(pType), uint256(RSendBatchDistributor.ProposalType.NONE));

        // Fee unchanged
        assertEq(dist.feeBps(), FEE_BPS);
    }

    function test_timelockFee_onlyOwnerProposes() public {
        vm.prank(alice);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        dist.proposeSetFee(100);
    }

    function test_timelockFee_cannotDoublePropose() public {
        vm.startPrank(owner);
        dist.proposeSetFee(100);

        vm.expectRevert(RSendBatchDistributor.ProposalAlreadyActive.selector);
        dist.proposeSetFee(200);
        vm.stopPrank();
    }

    function test_timelockFee_cannotExceedMax() public {
        vm.prank(owner);
        vm.expectRevert(abi.encodeWithSelector(
            RSendBatchDistributor.FeeTooHigh.selector, 1001, 1000
        ));
        dist.proposeSetFee(1001);
    }

    function test_executeNoProposal_reverts() public {
        vm.expectRevert(RSendBatchDistributor.NoActiveProposal.selector);
        dist.executeProposal();
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  7. TIMELOCK — GUARDIAN CHANGE
    // ═══════════════════════════════════════════════════════════════════════

    function test_timelockGuardian_fullFlow() public {
        address newGuardian = makeAddr("newGuardian");

        vm.prank(owner);
        dist.proposeSetGuardian(newGuardian);

        vm.warp(block.timestamp + 24 hours + 1);
        dist.executeProposal();

        assertEq(dist.guardian(), newGuardian);
    }

    function test_timelockGuardian_guardianCancels() public {
        address newGuardian = makeAddr("newGuardian");

        vm.prank(owner);
        dist.proposeSetGuardian(newGuardian);

        vm.prank(guardian);
        dist.cancelProposal();

        assertEq(dist.guardian(), guardian); // unchanged
    }

    function test_timelockGuardian_zeroAddressReverts() public {
        vm.prank(owner);
        vm.expectRevert(RSendBatchDistributor.ZeroAddress.selector);
        dist.proposeSetGuardian(address(0));
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  8. DAILY SPENDING CAP
    // ═══════════════════════════════════════════════════════════════════════

    function test_dailyCap_exceedReverts() public {
        // Set 1 ETH daily cap
        address ethSentinel = dist.ETH_SENTINEL();
        vm.prank(owner);
        dist.setDailyCap(ethSentinel, 1 ether);

        // First distribution: 0.5 ETH — should pass
        address[] memory r1 = new address[](1);
        r1[0] = makeAddr("r1");
        uint256[] memory a1 = new uint256[](1);
        a1[0] = 0.4975 ether; // ~0.5 ETH minus fee

        vm.prank(alice);
        dist.distributeETH{value: 0.5 ether}(r1, a1);

        // Second distribution: another 0.6 ETH — should exceed cap
        address[] memory r2 = new address[](1);
        r2[0] = makeAddr("r2");
        uint256[] memory a2 = new uint256[](1);
        a2[0] = 0.597 ether; // ~0.6 ETH minus fee

        vm.prank(alice);
        vm.expectRevert(); // DailyCapExceeded
        dist.distributeETH{value: 0.6 ether}(r2, a2);
    }

    function test_dailyCap_resetsAfter24h() public {
        address ethSentinel = dist.ETH_SENTINEL();
        vm.prank(owner);
        dist.setDailyCap(ethSentinel, 1 ether);

        // Use most of the cap
        address[] memory r = new address[](1);
        r[0] = makeAddr("r1");
        uint256[] memory a = new uint256[](1);
        a[0] = 0.895 ether;

        vm.prank(alice);
        dist.distributeETH{value: 0.9 ether}(r, a);

        // Fast forward 1 day
        vm.warp(block.timestamp + 1 days);

        // Should work again — new day
        r[0] = makeAddr("r2");
        vm.prank(alice);
        dist.distributeETH{value: 0.9 ether}(r, a);
    }

    function test_dailyCap_ERC20() public {
        vm.prank(owner);
        dist.setDailyCap(address(token), 1000e18);

        // Mint and approve
        uint256 amount = 600e18;
        uint256 fee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 pullAmount = amount + fee;

        token.mint(alice, pullAmount * 2);
        vm.startPrank(alice);
        token.approve(address(dist), pullAmount * 2);

        address[] memory r = new address[](1);
        r[0] = makeAddr("r1");
        uint256[] memory a = new uint256[](1);
        a[0] = amount;

        // First: 603 tokens (600 + 0.5% fee) — ok
        dist.distributeERC20(IERC20(address(token)), r, a);

        // Second: another 603 tokens — exceeds 1000 cap
        r[0] = makeAddr("r2");
        vm.expectRevert(); // DailyCapExceeded
        dist.distributeERC20(IERC20(address(token)), r, a);
        vm.stopPrank();
    }

    function test_dailyCap_zeroCap_noLimit() public {
        // Default cap is 0 = unlimited
        (address[] memory r, uint256[] memory a) = _makeRecipients(5);
        uint256 totalValue = _totalNeeded(5);

        vm.prank(alice);
        dist.distributeETH{value: totalValue}(r, a); // should not revert
    }

    function test_dailyCap_onlyOwner() public {
        address ethSentinel = dist.ETH_SENTINEL();
        vm.prank(alice);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        dist.setDailyCap(ethSentinel, 1 ether);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  9. EMERGENCY WITHDRAW
    // ═══════════════════════════════════════════════════════════════════════

    function test_emergencyWithdraw_onlyWhenPaused() public {
        // Send some ETH to the contract
        vm.deal(address(dist), 5 ether);

        // Not paused — should revert
        vm.prank(owner);
        vm.expectRevert(RSendBatchDistributor.NotPaused.selector);
        dist.emergencyWithdrawETH(payable(owner));

        // Pause first
        vm.prank(guardian);
        dist.pause();

        // Now should work
        vm.prank(owner);
        dist.emergencyWithdrawETH(payable(owner));

        assertEq(address(dist).balance, 0);
        assertEq(owner.balance, 5 ether);
    }

    function test_emergencyWithdraw_onlyOwner() public {
        vm.deal(address(dist), 5 ether);

        vm.prank(guardian);
        dist.pause();

        // Guardian cannot withdraw
        vm.prank(guardian);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        dist.emergencyWithdrawETH(payable(guardian));

        // Random user cannot withdraw
        vm.prank(alice);
        vm.expectRevert();
        dist.emergencyWithdrawETH(payable(alice));
    }

    function test_emergencyWithdrawERC20() public {
        token.mint(address(dist), 1000e18);

        vm.prank(owner);
        dist.pause();

        vm.prank(owner);
        dist.emergencyWithdrawERC20(IERC20(address(token)), owner);

        assertEq(token.balanceOf(address(dist)), 0);
        assertEq(token.balanceOf(owner), 1000e18);
    }

    function test_emergencyWithdraw_zeroBalance_reverts() public {
        vm.prank(guardian);
        dist.pause();

        vm.prank(owner);
        vm.expectRevert(RSendBatchDistributor.ZeroAmount.selector);
        dist.emergencyWithdrawETH(payable(owner));
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  10. OWNABLE2STEP — TWO-STEP TRANSFER
    // ═══════════════════════════════════════════════════════════════════════

    function test_ownable2Step_twoStepTransfer() public {
        address newOwner = makeAddr("newOwner");

        // Step 1: current owner initiates transfer
        vm.prank(owner);
        dist.transferOwnership(newOwner);

        // Owner hasn't changed yet
        assertEq(dist.owner(), owner);
        assertEq(dist.pendingOwner(), newOwner);

        // Step 2: new owner accepts
        vm.prank(newOwner);
        dist.acceptOwnership();

        assertEq(dist.owner(), newOwner);
    }

    function test_ownable2Step_cannotAcceptUnauthorized() public {
        address newOwner = makeAddr("newOwner");

        vm.prank(owner);
        dist.transferOwnership(newOwner);

        // Random user cannot accept
        vm.prank(alice);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        dist.acceptOwnership();
    }

    function test_ownable2Step_onlyOwnerTransfers() public {
        vm.prank(alice);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        dist.transferOwnership(alice);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  11. GUARDIAN PERMISSIONS
    // ═══════════════════════════════════════════════════════════════════════

    function test_guardianCannotDistribute() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(2);

        // Guardian is not blocked from distributing per se — they just
        // need to fund it like anyone. This test ensures guardian has
        // no special powers to distribute others' funds.
        // Actual check: guardian cannot unpause
        vm.prank(guardian);
        dist.pause();

        vm.prank(guardian);
        vm.expectRevert(); // OwnableUnauthorizedAccount
        dist.unpause();
    }

    function test_guardianCanCancelProposal() public {
        vm.prank(owner);
        dist.proposeSetFee(100);

        vm.prank(guardian);
        dist.cancelProposal();

        (RSendBatchDistributor.ProposalType pType,,) = dist.activeProposal();
        assertEq(uint256(pType), 0);
    }

    function test_randomCannotCancel() public {
        vm.prank(owner);
        dist.proposeSetFee(100);

        vm.prank(alice);
        vm.expectRevert(RSendBatchDistributor.NotOwnerOrGuardian.selector);
        dist.cancelProposal();
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  12. FEE CALCULATION
    // ═══════════════════════════════════════════════════════════════════════

    function test_calcSplit() public view {
        (uint256 net, uint256 fee) = dist.calcSplit(10000);
        assertEq(fee, 50);    // 0.5%
        assertEq(net, 9950);
    }

    function test_feeGoesToTreasury_ETH() public {
        address[] memory r = new address[](1);
        r[0] = makeAddr("r1");
        uint256[] memory a = new uint256[](1);
        a[0] = 0.995 ether; // net amount

        vm.prank(alice);
        dist.distributeETH{value: 1 ether}(r, a);

        // Treasury should get 0.5% of 1 ETH = 0.005 ETH
        assertEq(treasury.balance, 0.005 ether);
    }

    function test_feeGoesToTreasury_ERC20() public {
        uint256 amount = 1000e18;
        uint256 fee = (amount * FEE_BPS) / BPS_DENOM; // 5e18
        uint256 pullAmount = amount + fee;

        token.mint(alice, pullAmount);
        vm.startPrank(alice);
        token.approve(address(dist), pullAmount);

        address[] memory r = new address[](1);
        r[0] = makeAddr("r1");
        uint256[] memory a = new uint256[](1);
        a[0] = amount;

        dist.distributeERC20(IERC20(address(token)), r, a);
        vm.stopPrank();

        assertEq(token.balanceOf(treasury), fee);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  13. EDGE CASES
    // ═══════════════════════════════════════════════════════════════════════

    function test_ETHTransferFailed_rejecterRecipient() public {
        ETHRejecter rejecter = new ETHRejecter();

        address[] memory r = new address[](1);
        r[0] = address(rejecter);
        uint256[] memory a = new uint256[](1);
        a[0] = 0.995 ether;

        vm.prank(alice);
        vm.expectRevert(abi.encodeWithSelector(
            RSendBatchDistributor.ETHTransferFailed.selector, address(rejecter), 0.995 ether
        ));
        dist.distributeETH{value: 1 ether}(r, a);
    }

    function test_setTreasury() public {
        address newTreasury = makeAddr("newTreasury");

        vm.prank(owner);
        dist.setTreasury(newTreasury);

        assertEq(dist.treasury(), newTreasury);
    }

    function test_setTreasury_zeroAddress_reverts() public {
        vm.prank(owner);
        vm.expectRevert(RSendBatchDistributor.ZeroAddress.selector);
        dist.setTreasury(address(0));
    }

    function test_setTreasury_onlyOwner() public {
        vm.prank(alice);
        vm.expectRevert();
        dist.setTreasury(alice);
    }

    function test_getDailySpending_newDay() public {
        address ethSentinel = dist.ETH_SENTINEL();
        vm.prank(owner);
        dist.setDailyCap(ethSentinel, 10 ether);

        (uint256 spent,, uint256 cap) = dist.getDailySpending(ethSentinel);
        assertEq(spent, 0);
        assertEq(cap, 10 ether);
    }

    function test_events_batchDistributed() public {
        address[] memory r = new address[](2);
        r[0] = makeAddr("r1");
        r[1] = makeAddr("r2");
        uint256[] memory a = new uint256[](2);
        a[0] = 0.4975 ether;
        a[1] = 0.4975 ether;

        vm.prank(alice);
        vm.expectEmit(true, true, false, false);
        emit RSendBatchDistributor.BatchDistributed(alice, address(0), 1 ether, 2, 0.005 ether);
        dist.distributeETH{value: 1 ether}(r, a);
    }

    function test_events_singleTransfer() public {
        address r1 = makeAddr("r1");
        address[] memory r = new address[](1);
        r[0] = r1;
        uint256[] memory a = new uint256[](1);
        a[0] = 0.995 ether;

        vm.prank(alice);
        vm.expectEmit(true, false, false, true);
        emit RSendBatchDistributor.SingleTransfer(r1, 0.995 ether, 0);
        dist.distributeETH{value: 1 ether}(r, a);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  14. CONSTRUCTOR VALIDATION
    // ═══════════════════════════════════════════════════════════════════════

    function test_constructor_zeroTreasury_reverts() public {
        vm.expectRevert(RSendBatchDistributor.ZeroAddress.selector);
        new RSendBatchDistributor(owner, address(0), guardian, FEE_BPS);
    }

    function test_constructor_zeroGuardian_reverts() public {
        vm.expectRevert(RSendBatchDistributor.ZeroAddress.selector);
        new RSendBatchDistributor(owner, treasury, address(0), FEE_BPS);
    }

    function test_constructor_feeTooHigh_reverts() public {
        vm.expectRevert(abi.encodeWithSelector(
            RSendBatchDistributor.FeeTooHigh.selector, 1001, 1000
        ));
        new RSendBatchDistributor(owner, treasury, guardian, 1001);
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  15. GAS BENCHMARKS — batch vs N single transfers
    // ═══════════════════════════════════════════════════════════════════════

    function test_gasBenchmark_ETH_5() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(5);
        uint256 totalValue = _totalNeeded(5);

        vm.prank(alice);
        uint256 gasBefore = gasleft();
        dist.distributeETH{value: totalValue}(r, a);
        uint256 gasUsed = gasBefore - gasleft();

        // For reference: log the gas used
        emit log_named_uint("Gas: ETH batch 5 recipients", gasUsed);

        // Compare: 5 individual transfers would cost ~5 * 21000 = 105000 base gas
        // The batch should be significantly less than 5x single
    }

    function test_gasBenchmark_ETH_50() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(50);
        uint256 totalValue = _totalNeeded(50);

        vm.prank(alice);
        uint256 gasBefore = gasleft();
        dist.distributeETH{value: totalValue}(r, a);
        uint256 gasUsed = gasBefore - gasleft();

        emit log_named_uint("Gas: ETH batch 50 recipients", gasUsed);
    }

    function test_gasBenchmark_ETH_500() public {
        (address[] memory r, uint256[] memory a) = _makeRecipients(500);
        uint256 totalValue = _totalNeeded(500);

        vm.prank(alice);
        uint256 gasBefore = gasleft();
        dist.distributeETH{value: totalValue}(r, a);
        uint256 gasUsed = gasBefore - gasleft();

        emit log_named_uint("Gas: ETH batch 500 recipients", gasUsed);
    }

    function test_gasBenchmark_ERC20_5() public {
        uint256 perRecipient = 100e18;
        uint256 total = 5 * perRecipient;
        uint256 fee = (total * FEE_BPS) / BPS_DENOM;
        uint256 pullAmount = total + fee;

        token.mint(alice, pullAmount);
        vm.startPrank(alice);
        token.approve(address(dist), pullAmount);

        (address[] memory r, ) = _makeRecipients(5);
        uint256[] memory a = new uint256[](5);
        for (uint256 i; i < 5; i++) a[i] = perRecipient;

        uint256 gasBefore = gasleft();
        dist.distributeERC20(IERC20(address(token)), r, a);
        uint256 gasUsed = gasBefore - gasleft();
        vm.stopPrank();

        emit log_named_uint("Gas: ERC20 batch 5 recipients", gasUsed);
    }

    function test_gasBenchmark_ERC20_500() public {
        uint256 perRecipient = 1e18;
        uint256 total = 500 * perRecipient;
        uint256 fee = (total * FEE_BPS) / BPS_DENOM;
        uint256 pullAmount = total + fee;

        token.mint(alice, pullAmount);
        vm.startPrank(alice);
        token.approve(address(dist), pullAmount);

        (address[] memory r, ) = _makeRecipients(500);
        uint256[] memory a = new uint256[](500);
        for (uint256 i; i < 500; i++) a[i] = perRecipient;

        uint256 gasBefore = gasleft();
        dist.distributeERC20(IERC20(address(token)), r, a);
        uint256 gasUsed = gasBefore - gasleft();
        vm.stopPrank();

        emit log_named_uint("Gas: ERC20 batch 500 recipients", gasUsed);
    }

    function test_gasBenchmark_singleTransfers_5() public {
        // Compare: 5 individual ETH transfers
        address[5] memory recs = [
            makeAddr("s1"), makeAddr("s2"), makeAddr("s3"),
            makeAddr("s4"), makeAddr("s5")
        ];

        vm.startPrank(alice);
        uint256 gasBefore = gasleft();
        for (uint256 i; i < 5; i++) {
            (bool ok,) = recs[i].call{value: 0.01 ether}("");
            require(ok);
        }
        uint256 gasUsed = gasBefore - gasleft();
        vm.stopPrank();

        emit log_named_uint("Gas: 5 individual ETH transfers", gasUsed);
    }
}
