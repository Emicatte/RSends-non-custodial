// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import "../src/RSendsRouter.sol"; // brings in RSendsRouter + the file-level errors

import {ERC20}       from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";
import {Ownable}     from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable}    from "@openzeppelin/contracts/utils/Pausable.sol";

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

    function transfer(address to, uint256 amount) external {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount; // no return value
    }

    function transferFrom(address from, address to, uint256 amount) external {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount; // no return value
    }
}

/// Fee-on-transfer token: recipient receives less than `value` (1% burned in transit).
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
    RSendsRouter public immutable router;
    bool public reentryAttempted;
    bool public reentryReverted;
    bool public reentrySucceeded;

    constructor(RSendsRouter r) { router = r; }

    receive() external payable {
        if (reentryAttempted) return;
        reentryAttempted = true;
        // value matches amount + fee(0), so the ONLY reason this can revert is the guard.
        try router.payNative{value: 1}(bytes32(uint256(1)), payable(address(0xBEEF)), 1, 0) {
            reentrySucceeded = true;
        } catch {
            reentryReverted = true;
        }
    }
}

/*//////////////////////////////////////////////////////////////
                              TESTS
//////////////////////////////////////////////////////////////*/

contract RSendsRouterTest is Test {
    // mirror of the contract event for expectEmit
    event PaymentMade(
        bytes32 indexed invoiceId, address indexed merchant, address indexed payer,
        address token, uint256 amount, uint256 fee, uint256 blockTimestamp
    );

    RSendsRouter router;
    MockERC20Permit token;

    // Locked EUR-stable pricing in 6-decimal minimal units: €0.15 flat, €1.15 at/above €1,000.
    uint256 constant BASE      = 150_000;        // €0.15
    uint256 constant THRESHOLD = 1_000_000_000;  // €1,000
    uint256 constant SURCHARGE = 1_000_000;      // €1.00 -> at/above fee = 1_150_000 (€1.15)

    uint256 constant FEE_BELOW = BASE;               // 150_000
    uint256 constant FEE_ABOVE = BASE + SURCHARGE;   // 1_150_000

    uint256 constant AMT_BELOW = 100_000_000;        // €100
    uint256 constant AMT_ABOVE = 5_000_000_000;      // €5,000

    uint256 internal constant PAYER_PK = 0xA11CE;
    address internal payer;
    address internal owner        = makeAddr("owner");
    address internal feeCollector = makeAddr("feeCollector");
    address internal merchant     = makeAddr("merchant");

    bytes32 internal constant INVOICE = keccak256("invoice-1");

    function setUp() public {
        payer = vm.addr(PAYER_PK);
        vm.warp(1_700_000_000); // stable block.timestamp for event assertions

        vm.prank(owner);
        router = new RSendsRouter(owner, feeCollector);

        token = new MockERC20Permit();
        vm.prank(owner);
        router.setFeeConfig(address(token), BASE, THRESHOLD, SURCHARGE, true);

        token.mint(payer, 1_000_000 * 1e6);
    }

    function _approve(address spender, uint256 amount) internal {
        vm.prank(payer);
        token.approve(spender, amount);
    }

    /*//////////////////// quoteFee ////////////////////*/

    function test_quoteFee_belowThreshold() public view {
        assertEq(router.quoteFee(address(token), THRESHOLD - 1), FEE_BELOW);
        assertEq(router.quoteFee(address(token), AMT_BELOW), FEE_BELOW);
    }

    function test_quoteFee_atThreshold_inclusive() public view {
        assertEq(router.quoteFee(address(token), THRESHOLD), FEE_ABOVE);
    }

    function test_quoteFee_aboveThreshold() public view {
        assertEq(router.quoteFee(address(token), AMT_ABOVE), FEE_ABOVE);
    }

    /// Verifies the locked pricing is exactly €0.15 / €1.15 (never a percentage).
    function test_quoteFee_exactDecidedPricing() public view {
        assertEq(FEE_BELOW, 150_000);   // €0.15
        assertEq(FEE_ABOVE, 1_150_000); // €1.15
        // fee is flat, not proportional: 8x the amount (still below threshold) -> same fee.
        assertEq(router.quoteFee(address(token), AMT_BELOW), router.quoteFee(address(token), AMT_BELOW * 8));
    }

    function testFuzz_quoteFee(uint256 amount) public view {
        uint256 expected = amount >= THRESHOLD ? FEE_ABOVE : FEE_BELOW;
        assertEq(router.quoteFee(address(token), amount), expected);
    }

    /*//////////////////// pay: happy paths ////////////////////*/

    function test_pay_belowThreshold_transfersAndEmits() public {
        _approve(address(router), AMT_BELOW + FEE_BELOW);

        vm.expectEmit(true, true, true, true, address(router));
        emit PaymentMade(INVOICE, merchant, payer, address(token), AMT_BELOW, FEE_BELOW, block.timestamp);

        vm.prank(payer);
        router.pay(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW);

        assertEq(token.balanceOf(merchant), AMT_BELOW);
        assertEq(token.balanceOf(feeCollector), FEE_BELOW);
        assertEq(token.balanceOf(address(router)), 0); // non-custodial: router holds nothing
    }

    function test_pay_aboveThreshold_transfersAndEmits() public {
        _approve(address(router), AMT_ABOVE + FEE_ABOVE);

        vm.expectEmit(true, true, true, true, address(router));
        emit PaymentMade(INVOICE, merchant, payer, address(token), AMT_ABOVE, FEE_ABOVE, block.timestamp);

        vm.prank(payer);
        router.pay(INVOICE, merchant, address(token), AMT_ABOVE, FEE_ABOVE);

        assertEq(token.balanceOf(merchant), AMT_ABOVE);
        assertEq(token.balanceOf(feeCollector), FEE_ABOVE);
        assertEq(token.balanceOf(address(router)), 0);
    }

    /*//////////////////// pay: reverts ////////////////////*/

    function test_pay_revert_zeroAmount() public {
        _approve(address(router), type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(ZeroAmount.selector);
        router.pay(INVOICE, merchant, address(token), 0, FEE_BELOW);
    }

    function test_pay_revert_zeroMerchant() public {
        _approve(address(router), type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(ZeroMerchant.selector);
        router.pay(INVOICE, address(0), address(token), AMT_BELOW, FEE_BELOW);
    }

    function test_pay_revert_zeroToken() public {
        vm.prank(payer);
        vm.expectRevert(abi.encodeWithSelector(UnsupportedToken.selector, address(0)));
        router.pay(INVOICE, merchant, address(0), AMT_BELOW, FEE_BELOW);
    }

    function test_pay_revert_unsupportedToken() public {
        MockERC20Permit other = new MockERC20Permit(); // never configured -> enabled == false
        other.mint(payer, 1e18);
        vm.prank(payer);
        other.approve(address(router), type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(abi.encodeWithSelector(UnsupportedToken.selector, address(other)));
        router.pay(INVOICE, merchant, address(other), AMT_BELOW, FEE_BELOW);
    }

    function test_pay_revert_disabledToken() public {
        vm.prank(owner);
        router.setFeeConfig(address(token), BASE, THRESHOLD, SURCHARGE, false); // disable
        _approve(address(router), type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(abi.encodeWithSelector(UnsupportedToken.selector, address(token)));
        router.pay(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW);
    }

    function test_pay_revert_whenPaused() public {
        vm.prank(owner);
        router.pause();
        _approve(address(router), type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        router.pay(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW);
    }

    function test_pay_revert_insufficientAllowance_missingFee() public {
        _approve(address(router), AMT_BELOW); // approved only the amount, not the fee
        vm.prank(payer);
        vm.expectRevert(); // OZ ERC20InsufficientAllowance on the fee transfer
        router.pay(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW);
        // amount-only allowance means nothing settled
        assertEq(token.balanceOf(merchant), 0);
        assertEq(token.balanceOf(feeCollector), 0);
    }

    /*//////////////////// pay: maxFee ceiling ////////////////////*/

    function test_pay_maxFee_succeedsWhenFeeWithinCeiling() public {
        _approve(address(router), AMT_BELOW + FEE_BELOW);
        vm.prank(payer);
        router.pay(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW); // maxFee == fee, ok
        assertEq(token.balanceOf(feeCollector), FEE_BELOW);
    }

    function test_pay_maxFee_revertsWhenFeeAboveCeiling() public {
        _approve(address(router), type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(FeeTooHigh.selector);
        router.pay(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW - 1); // ceiling too low
    }

    /// Owner raises the fee config between the payer's quote and submit -> FeeTooHigh protects payer.
    function test_pay_maxFee_revertsWhenOwnerRaisesFeeAfterQuote() public {
        uint256 quotedMaxFee = router.quoteFee(address(token), AMT_BELOW); // payer signs against this
        _approve(address(router), type(uint256).max);

        vm.prank(owner);
        router.setFeeConfig(address(token), BASE * 2, THRESHOLD, SURCHARGE, true); // fee raised

        vm.prank(payer);
        vm.expectRevert(FeeTooHigh.selector);
        router.pay(INVOICE, merchant, address(token), AMT_BELOW, quotedMaxFee);
    }

    /*//////////////////// USDT-style / fee-on-transfer ////////////////////*/

    function test_pay_usdtStyleNoReturnValue() public {
        MockUSDTNoReturn usdt = new MockUSDTNoReturn();
        vm.prank(owner);
        router.setFeeConfig(address(usdt), BASE, THRESHOLD, SURCHARGE, true);

        usdt.mint(payer, 1_000_000_000);
        vm.prank(payer);
        usdt.approve(address(router), AMT_BELOW + FEE_BELOW);

        vm.prank(payer);
        router.pay(INVOICE, merchant, address(usdt), AMT_BELOW, FEE_BELOW);

        assertEq(usdt.balanceOf(merchant), AMT_BELOW);
        assertEq(usdt.balanceOf(feeCollector), FEE_BELOW);
    }

    /// Documents why fee-on-transfer tokens must NEVER be whitelisted: merchant is short-changed.
    function test_pay_feeOnTransfer_merchantReceivesLess() public {
        MockFeeOnTransfer fot = new MockFeeOnTransfer();
        vm.prank(owner);
        router.setFeeConfig(address(fot), 0, 0, 0, true); // zero router fee to isolate the token's cut

        fot.mint(payer, 1e24);
        vm.prank(payer);
        fot.approve(address(router), type(uint256).max);

        uint256 amount = 1_000e18;
        vm.prank(payer);
        router.pay(INVOICE, merchant, address(fot), amount, 0);

        assertLt(fot.balanceOf(merchant), amount); // received strictly less than `amount`
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

    function test_payWithPermit_happyPath() public {
        uint256 total = AMT_BELOW + FEE_BELOW;
        uint256 deadline = block.timestamp + 1 hours;
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(total, deadline);

        // no prior approve: the permit grants the allowance in the same tx
        vm.prank(payer);
        router.payWithPermit(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW, deadline, v, r, s);

        assertEq(token.balanceOf(merchant), AMT_BELOW);
        assertEq(token.balanceOf(feeCollector), FEE_BELOW);
    }

    function test_payWithPermit_expiredDeadline_revertsNoAllowance() public {
        uint256 total = AMT_BELOW + FEE_BELOW;
        uint256 deadline = block.timestamp - 1; // already expired
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(total, deadline);

        // permit reverts (expired) -> swallowed by try/catch -> no allowance -> transferFrom reverts
        vm.prank(payer);
        vm.expectRevert();
        router.payWithPermit(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW, deadline, v, r, s);

        assertEq(token.balanceOf(merchant), 0);
    }

    /// Front-run resilience: an allowance already exists; a useless/expired permit is swallowed
    /// and the payment still succeeds.
    function test_payWithPermit_frontRun_existingAllowanceSucceeds() public {
        _approve(address(router), AMT_BELOW + FEE_BELOW); // allowance already in place

        // garbage / expired permit args — must be swallowed
        uint256 deadline = block.timestamp - 1;
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(AMT_BELOW + FEE_BELOW, deadline);

        vm.prank(payer);
        router.payWithPermit(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW, deadline, v, r, s);

        assertEq(token.balanceOf(merchant), AMT_BELOW);
        assertEq(token.balanceOf(feeCollector), FEE_BELOW);
    }

    /*//////////////////// payNative ////////////////////*/

    function test_payNative_zeroFee_happyPath() public {
        uint256 amount = 2 ether;
        vm.deal(payer, amount);

        uint256 merchantBefore = merchant.balance;
        vm.prank(payer);
        router.payNative{value: amount}(INVOICE, payable(merchant), amount, 0);

        assertEq(merchant.balance, merchantBefore + amount);
        assertEq(address(router).balance, 0);
    }

    function test_payNative_nonZeroFee() public {
        uint256 nativeFee = 0.01 ether;
        vm.prank(owner);
        router.setFeeConfig(address(0), nativeFee, 0, 0, true);

        uint256 amount = 1 ether;
        vm.deal(payer, amount + nativeFee);

        uint256 merchantBefore = merchant.balance;
        uint256 collectorBefore = feeCollector.balance;

        vm.prank(payer);
        router.payNative{value: amount + nativeFee}(INVOICE, payable(merchant), amount, nativeFee);

        assertEq(merchant.balance, merchantBefore + amount);
        assertEq(feeCollector.balance, collectorBefore + nativeFee);
        assertEq(address(router).balance, 0);
    }

    function test_payNative_revert_wrongValue() public {
        uint256 amount = 1 ether;
        vm.deal(payer, amount + 1);
        vm.prank(payer);
        vm.expectRevert(WrongNativeValue.selector);
        router.payNative{value: amount + 1}(INVOICE, payable(merchant), amount, 0); // fee 0, value != amount
    }

    function test_payNative_revert_rejectingMerchant() public {
        RejectingMerchant bad = new RejectingMerchant();
        uint256 amount = 1 ether;
        vm.deal(payer, amount);
        vm.prank(payer);
        vm.expectRevert(NativeTransferFailed.selector);
        router.payNative{value: amount}(INVOICE, payable(address(bad)), amount, 0);
    }

    /// Reentrancy: malicious merchant re-enters payNative on receive(); the re-entry is rejected
    /// by the guard, yet the outer payment completes and the merchant keeps the funds.
    function test_payNative_reentrancyBlocked_outerCompletes() public {
        ReentrantMerchant evil = new ReentrantMerchant(router);
        uint256 amount = 1 ether;
        vm.deal(payer, amount);

        vm.prank(payer);
        router.payNative{value: amount}(INVOICE, payable(address(evil)), amount, 0);

        assertTrue(evil.reentryAttempted());
        assertTrue(evil.reentryReverted());
        assertFalse(evil.reentrySucceeded());
        assertEq(address(evil).balance, amount); // outer payment landed; re-entry sent nothing out
        assertEq(address(router).balance, 0);
    }

    /*//////////////////// access control ////////////////////*/

    function test_setFeeConfig_onlyOwner() public {
        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, attacker));
        router.setFeeConfig(address(token), 1, 2, 3, true);
    }

    function test_setFeeCollector_onlyOwner() public {
        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, attacker));
        router.setFeeCollector(attacker);
    }

    function test_pause_onlyOwner() public {
        address attacker = makeAddr("attacker");
        vm.prank(attacker);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, attacker));
        router.pause();
    }

    function test_setFeeCollector_revert_zeroAddress() public {
        vm.prank(owner);
        vm.expectRevert(ZeroAddress.selector);
        router.setFeeCollector(address(0));
    }

    function test_setFeeCollector_updates() public {
        address newCollector = makeAddr("newCollector");
        vm.prank(owner);
        router.setFeeCollector(newCollector);
        assertEq(router.feeCollector(), newCollector);
    }

    function test_pause_unpause_flow() public {
        vm.prank(owner);
        router.pause();
        assertTrue(router.paused());
        vm.prank(owner);
        router.unpause();
        assertFalse(router.paused());

        _approve(address(router), AMT_BELOW + FEE_BELOW);
        vm.prank(payer);
        router.pay(INVOICE, merchant, address(token), AMT_BELOW, FEE_BELOW); // works again
        assertEq(token.balanceOf(merchant), AMT_BELOW);
    }

    /*//////////////////// fuzz: pay ////////////////////*/

    function testFuzz_pay_balances(uint256 amount) public {
        amount = bound(amount, 1, 1_000_000 * 1e6);
        uint256 fee = router.quoteFee(address(token), amount);

        token.mint(payer, amount + fee); // ensure funds on top of setUp mint
        _approve(address(router), amount + fee);

        uint256 merchantBefore = token.balanceOf(merchant);
        uint256 collectorBefore = token.balanceOf(feeCollector);

        vm.prank(payer);
        router.pay(INVOICE, merchant, address(token), amount, type(uint256).max);

        assertEq(token.balanceOf(merchant), merchantBefore + amount);
        assertEq(token.balanceOf(feeCollector), collectorBefore + fee);
        assertEq(token.balanceOf(address(router)), 0);
    }
}
