// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import "../src/RSendsRouterV2.sol"; // brings in RSendsRouterV2 + the file-level errors

import {ERC20}       from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

/*//////////////////////////////////////////////////////////////
                              MOCKS
//////////////////////////////////////////////////////////////*/

/// Standard EIP-2612 ERC20 (real permit, usable as a plain ERC20 too).
contract MockERC20Permit is ERC20, ERC20Permit {
    constructor() ERC20("Mock USD", "mUSD") ERC20Permit("Mock USD") {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }
}

/// USDT-style token: transfer/transferFrom/approve return NOTHING. Must work via SafeERC20.
contract MockUSDTNoReturn {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }

    function approve(address spender, uint256 amount) external {
        allowance[msg.sender][spender] = amount; // no return value
    }

    function transferFrom(address from, address to, uint256 amount) external {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount; // no return value
    }
}

/// Fee-on-transfer token: the merchant receives less than `amount`. The v2
/// router does NOT gate this (no whitelist exists) — the only gate is
/// off-chain at intent creation (token registry). See AUDIT_HANDOFF_ROUTERV2.md.
contract MockFeeOnTransfer is ERC20 {
    uint256 public constant FEE_BPS = 100; // 1%
    constructor() ERC20("FeeOnTransfer", "FOT") {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }

    function _update(address from, address to, uint256 value) internal override {
        if (from != address(0) && to != address(0)) {
            uint256 cut = (value * FEE_BPS) / 10_000;
            super._update(from, to, value - cut);
            super._update(from, address(0), cut); // burn the in-transit cut
        } else {
            super._update(from, to, value);
        }
    }
}

/// Merchant that rejects native ETH → forces NativeTransferFailed.
contract RejectingMerchant {
    receive() external payable { revert("no ETH"); }
}

/// Malicious merchant: re-enters payNative on receive() but swallows the revert,
/// so the outer payment can still complete while the re-entry is rejected.
contract ReentrantMerchant {
    RSendsRouterV2 public immutable router;
    bool public reentryAttempted;
    bool public reentryReverted;
    bool public reentrySucceeded;

    constructor(RSendsRouterV2 r) { router = r; }

    receive() external payable {
        if (reentryAttempted) return;
        reentryAttempted = true;
        // value matches amount exactly, so the ONLY reason this can revert is the guard.
        try router.payNative{value: 1}(bytes32(uint256(1)), payable(address(0xBEEF)), 1) {
            reentrySucceeded = true;
        } catch {
            reentryReverted = true;
        }
    }
}

/*//////////////////////////////////////////////////////////////
                              TESTS
//////////////////////////////////////////////////////////////*/

contract RSendsRouterV2Test is Test {
    // mirror of the contract event for expectEmit — 6 args, NO fee word
    event PaymentMade(
        bytes32 indexed invoiceId, address indexed merchant, address indexed payer,
        address token, uint256 amount, uint256 blockTimestamp
    );

    RSendsRouterV2 router;
    MockERC20Permit token;

    uint256 internal constant PAYER_PK = 0xA11CE;
    address internal payer;
    address internal merchant = makeAddr("merchant");

    bytes32 internal constant INVOICE = keccak256("v2-invoice-1");
    uint256 internal constant AMT = 250_000_000; // 250 USDC (6 dec)

    function setUp() public {
        payer = vm.addr(PAYER_PK);
        vm.warp(1_700_000_000); // stable block.timestamp for event assertions

        router = new RSendsRouterV2();
        token = new MockERC20Permit();
        token.mint(payer, 1_000_000 * 1e6);
        vm.deal(payer, 1_000 ether);
    }

    function _approve(uint256 amount) internal {
        vm.prank(payer);
        token.approve(address(router), amount);
    }

    /*//////////////////// event-shape pin (cross-stack) ////////////////////*/

    /// The backend indexer pins this exact hash (test_indexer_topic_hashes.py).
    /// If this test moves, the indexer decode moves in the same PR — or mainnet
    /// payments become invisible.
    function test_eventTopic_pinnedLiteral() public pure {
        assertEq(
            keccak256("PaymentMade(bytes32,address,address,address,uint256,uint256)"),
            bytes32(0xc3e210e146bbcd43de924ac66fa9d284db14f167144f83b2bcf40a40cc843241)
        );
    }

    /*//////////////////// pay: single-transfer invariant ////////////////////*/

    function test_pay_singleTransfer_exactAmounts_andEmits() public {
        _approve(AMT);
        uint256 payerBefore = token.balanceOf(payer);

        vm.expectEmit(true, true, true, true);
        emit PaymentMade(INVOICE, merchant, payer, address(token), AMT, block.timestamp);

        vm.prank(payer);
        router.pay(INVOICE, merchant, address(token), AMT);

        assertEq(token.balanceOf(merchant), AMT, "merchant receives exactly amount");
        assertEq(token.balanceOf(payer), payerBefore - AMT, "payer parts with exactly amount");
        assertEq(token.balanceOf(address(router)), 0, "router token balance stays zero");
        assertEq(address(router).balance, 0, "router ETH balance stays zero");
    }

    function test_pay_usdtStyleNoReturnToken() public {
        MockUSDTNoReturn usdt = new MockUSDTNoReturn();
        usdt.mint(payer, AMT);
        vm.prank(payer);
        usdt.approve(address(router), AMT);

        vm.prank(payer);
        router.pay(INVOICE, merchant, address(usdt), AMT);

        assertEq(usdt.balanceOf(merchant), AMT);
        assertEq(usdt.balanceOf(address(router)), 0);
    }

    function testFuzz_pay_conservation(uint96 rawAmount) public {
        uint256 amount = bound(uint256(rawAmount), 1, token.balanceOf(payer));
        _approve(amount);
        uint256 payerBefore = token.balanceOf(payer);

        vm.prank(payer);
        router.pay(INVOICE, merchant, address(token), amount);

        assertEq(token.balanceOf(merchant), amount);
        assertEq(token.balanceOf(payer), payerBefore - amount);
        assertEq(token.balanceOf(address(router)), 0);
    }

    /*//////////////////// pay: reverts ////////////////////*/

    function test_pay_revert_zeroMerchant() public {
        _approve(AMT);
        vm.prank(payer);
        vm.expectRevert(ZeroMerchant.selector);
        router.pay(INVOICE, address(0), address(token), AMT);
    }

    function test_pay_revert_zeroAmount() public {
        vm.prank(payer);
        vm.expectRevert(ZeroAmount.selector);
        router.pay(INVOICE, merchant, address(token), 0);
    }

    function test_pay_revert_zeroToken() public {
        vm.prank(payer);
        vm.expectRevert(ZeroToken.selector);
        router.pay(INVOICE, merchant, address(0), AMT);
    }

    function test_pay_revert_insufficientAllowance() public {
        // no approve at all
        vm.prank(payer);
        vm.expectRevert();
        router.pay(INVOICE, merchant, address(token), AMT);
    }

    /*//////////////////// payNative ////////////////////*/

    function test_payNative_exactValue_transfersAndEmits() public {
        uint256 amount = 1 ether;
        uint256 merchantBefore = merchant.balance;

        vm.expectEmit(true, true, true, true);
        emit PaymentMade(INVOICE, merchant, payer, address(0), amount, block.timestamp);

        vm.prank(payer);
        router.payNative{value: amount}(INVOICE, payable(merchant), amount);

        assertEq(merchant.balance, merchantBefore + amount);
        assertEq(address(router).balance, 0, "router never holds ETH");
    }

    function testFuzz_payNative_conservation(uint96 rawAmount) public {
        uint256 amount = bound(uint256(rawAmount), 1, payer.balance);
        uint256 merchantBefore = merchant.balance;

        vm.prank(payer);
        router.payNative{value: amount}(INVOICE, payable(merchant), amount);

        assertEq(merchant.balance, merchantBefore + amount);
        assertEq(address(router).balance, 0);
    }

    function test_payNative_revert_wrongValue() public {
        vm.startPrank(payer);
        vm.expectRevert(WrongNativeValue.selector);
        router.payNative{value: 1 ether - 1}(INVOICE, payable(merchant), 1 ether);

        vm.expectRevert(WrongNativeValue.selector);
        router.payNative{value: 1 ether + 1}(INVOICE, payable(merchant), 1 ether);

        vm.expectRevert(WrongNativeValue.selector);
        router.payNative{value: 0}(INVOICE, payable(merchant), 1 ether);
        vm.stopPrank();
    }

    function test_payNative_revert_zeroMerchant() public {
        vm.prank(payer);
        vm.expectRevert(ZeroMerchant.selector);
        router.payNative{value: 1 ether}(INVOICE, payable(address(0)), 1 ether);
    }

    function test_payNative_revert_zeroAmount() public {
        vm.prank(payer);
        vm.expectRevert(ZeroAmount.selector);
        router.payNative{value: 0}(INVOICE, payable(merchant), 0);
    }

    function test_payNative_revert_rejectingMerchant() public {
        RejectingMerchant rejector = new RejectingMerchant();
        vm.prank(payer);
        vm.expectRevert(NativeTransferFailed.selector);
        router.payNative{value: 1 ether}(INVOICE, payable(address(rejector)), 1 ether);
    }

    /// Re-entry from the merchant's receive() is blocked by nonReentrant; the
    /// outer payment completes because the malicious merchant swallows the revert.
    function test_payNative_reentrancyBlocked() public {
        ReentrantMerchant evil = new ReentrantMerchant(router);
        vm.deal(address(evil), 1); // gas money for its inner attempt

        vm.prank(payer);
        router.payNative{value: 1 ether}(INVOICE, payable(address(evil)), 1 ether);

        assertTrue(evil.reentryAttempted(), "re-entry was attempted");
        assertTrue(evil.reentryReverted(), "re-entry was rejected by the guard");
        assertFalse(evil.reentrySucceeded(), "re-entry never succeeded");
        assertEq(address(router).balance, 0);
    }

    /*//////////////////// payWithPermit ////////////////////*/

    function _signPermit(uint256 value, uint256 deadline) internal view returns (uint8 v, bytes32 r, bytes32 s) {
        bytes32 permitTypehash =
            keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)");
        bytes32 structHash = keccak256(
            abi.encode(permitTypehash, payer, address(router), value, token.nonces(payer), deadline)
        );
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", token.DOMAIN_SEPARATOR(), structHash));
        (v, r, s) = vm.sign(PAYER_PK, digest);
    }

    /// Permit value is EXACTLY the amount — there is no fee term to add.
    function test_payWithPermit_noPriorAllowance_permitValueIsExactlyAmount() public {
        uint256 deadline = block.timestamp + 1 hours;
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(AMT, deadline);

        vm.expectEmit(true, true, true, true);
        emit PaymentMade(INVOICE, merchant, payer, address(token), AMT, block.timestamp);

        vm.prank(payer);
        router.payWithPermit(INVOICE, merchant, address(token), AMT, deadline, v, r, s);

        assertEq(token.balanceOf(merchant), AMT);
        assertEq(token.allowance(payer, address(router)), 0, "permit allowance fully consumed");
        assertEq(token.balanceOf(address(router)), 0);
    }

    /// Front-run/consumed permit: the try/catch swallows the failed permit and
    /// the existing allowance covers the transfer.
    function test_payWithPermit_consumedPermit_fallsBackToAllowance() public {
        uint256 deadline = block.timestamp + 1 hours;
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(AMT, deadline);

        // front-runner consumes the signature first
        token.permit(payer, address(router), AMT, deadline, v, r, s);
        assertEq(token.allowance(payer, address(router)), AMT);

        vm.prank(payer);
        router.payWithPermit(INVOICE, merchant, address(token), AMT, deadline, v, r, s);

        assertEq(token.balanceOf(merchant), AMT);
    }

    function test_payWithPermit_garbageSig_noAllowance_reverts() public {
        uint256 deadline = block.timestamp + 1 hours;
        vm.prank(payer);
        vm.expectRevert();
        router.payWithPermit(INVOICE, merchant, address(token), AMT, deadline, 27, bytes32(uint256(1)), bytes32(uint256(2)));

        assertEq(token.balanceOf(merchant), 0);
    }

    function test_payWithPermit_revert_zeroToken() public {
        vm.prank(payer);
        vm.expectRevert(ZeroToken.selector);
        router.payWithPermit(INVOICE, merchant, address(0), AMT, block.timestamp, 0, bytes32(0), bytes32(0));
    }

    /*//////////////////// fee-on-transfer (documented, not gated) ////////////////////*/

    /// v2 twin of v1's test_pay_feeOnTransfer_merchantReceivesLess: with no
    /// on-chain whitelist the contract does NOT protect against FoT tokens —
    /// the load-bearing gate is off-chain intent-creation validation.
    function test_pay_feeOnTransfer_merchantReceivesLess() public {
        MockFeeOnTransfer fot = new MockFeeOnTransfer();
        fot.mint(payer, 1e24);
        vm.prank(payer);
        fot.approve(address(router), type(uint256).max);

        uint256 amount = 1_000e18;
        vm.prank(payer);
        router.pay(INVOICE, merchant, address(fot), amount);

        assertLt(fot.balanceOf(merchant), amount); // received strictly less than `amount`
        assertEq(fot.balanceOf(address(router)), 0);
    }

    /*//////////////////// no-owner negatives ////////////////////*/

    /// Every owner/fee selector of v1, verbatim. None may exist on v2: with no
    /// fallback, each raw call MUST fail. This test documents what was removed.
    function test_noOwnerSurface_v1SelectorsAllRevert() public {
        bytes[] memory calls = new bytes[](10);
        calls[0] = abi.encodeWithSignature("owner()");
        calls[1] = abi.encodeWithSignature("pendingOwner()");
        calls[2] = abi.encodeWithSignature("pause()");
        calls[3] = abi.encodeWithSignature("unpause()");
        calls[4] = abi.encodeWithSignature("paused()");
        calls[5] = abi.encodeWithSignature(
            "setFeeConfig(address,uint256,uint256,uint256,bool)", address(token), 0, 0, 0, true
        );
        calls[6] = abi.encodeWithSignature("setFeeCollector(address)", address(this));
        calls[7] = abi.encodeWithSignature("feeCollector()");
        calls[8] = abi.encodeWithSignature("quoteFee(address,uint256)", address(token), AMT);
        calls[9] = abi.encodeWithSignature("transferOwnership(address)", address(this));

        for (uint256 i; i < calls.length; ++i) {
            (bool ok, ) = address(router).call(calls[i]);
            assertFalse(ok, "owner or fee selector answered: admin surface exists");
        }
    }

    /*//////////////////// no-custody negatives ////////////////////*/

    function test_plainEthSend_reverts_noReceive() public {
        vm.prank(payer);
        (bool ok, ) = address(router).call{value: 1 ether}("");
        assertFalse(ok, "router accepted plain ETH: receive or fallback exists");
        assertEq(address(router).balance, 0);
    }

    /// Even a force-fed balance (vm.deal simulates selfdestruct-style forcing)
    /// is unreachable: no selector exists that moves value out, so the payment
    /// paths remain correct and the balance is provably stuck, not custodied.
    function test_forcedBalance_isUnreachable_paymentsUnaffected() public {
        vm.deal(address(router), 1 ether);

        _approve(AMT);
        vm.prank(payer);
        router.pay(INVOICE, merchant, address(token), AMT);
        assertEq(token.balanceOf(merchant), AMT);

        uint256 amount = 2 ether;
        vm.prank(payer);
        router.payNative{value: amount}(INVOICE, payable(merchant), amount);

        assertEq(address(router).balance, 1 ether, "forced balance untouched: no path moves it");
    }
}
