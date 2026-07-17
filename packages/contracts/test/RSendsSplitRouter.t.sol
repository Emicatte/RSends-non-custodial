// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import "../src/RSendsSplitRouter.sol"; // brings in RSendsSplitRouter + the file-level errors

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

/// Blocklisting token: transfers to a blocked address revert (USDC-style blacklist).
/// Used to prove a split is all-or-nothing when ONE leg cannot receive.
contract MockBlocklistToken is ERC20 {
    mapping(address => bool) public blocked;
    constructor() ERC20("Blocklist USD", "bUSD") {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }
    function setBlocked(address who, bool isBlocked) external { blocked[who] = isBlocked; }

    function _update(address from, address to, uint256 value) internal override {
        require(!blocked[to], "recipient blocked");
        super._update(from, to, value);
    }
}

/// Recipient that rejects native ETH → forces NativeTransferFailed on its leg.
contract RejectingRecipient {
    receive() external payable { revert("no ETH"); }
}

/// Malicious recipient: re-enters paySplitNative on receive() but swallows the revert,
/// so the outer split can still complete while the re-entry is rejected.
contract ReentrantRecipient {
    RSendsSplitRouter public immutable router;
    bool public reentryAttempted;
    bool public reentryReverted;
    bool public reentrySucceeded;

    constructor(RSendsSplitRouter r) { router = r; }

    receive() external payable {
        if (reentryAttempted) return;
        reentryAttempted = true;
        address payable[] memory rcpts = new address payable[](2);
        rcpts[0] = payable(address(0xBEEF));
        rcpts[1] = payable(address(0xCAFE));
        uint16[] memory bps = new uint16[](2);
        bps[0] = 5000;
        bps[1] = 5000;
        // value matches totalAmount, so the ONLY reason this can revert is the guard.
        try router.paySplitNative{value: 2}(bytes32(uint256(1)), 2, rcpts, bps) {
            reentrySucceeded = true;
        } catch {
            reentryReverted = true;
        }
    }
}

/*//////////////////////////////////////////////////////////////
                              TESTS
//////////////////////////////////////////////////////////////*/

contract RSendsSplitRouterTest is Test {
    // mirror of the contract event for expectEmit
    event SplitPaymentMade(
        bytes32 indexed invoiceId, address indexed payer,
        address token, uint256 totalAmount,
        address[] recipients, uint256[] amounts, uint256 blockTimestamp
    );

    RSendsSplitRouter router;
    MockERC20Permit token;

    uint256 internal constant PAYER_PK = 0xA11CE;
    address internal payer;
    address internal alice = makeAddr("alice"); // position 0 = primary (gets remainder)
    address internal bob   = makeAddr("bob");
    address internal carol = makeAddr("carol");

    bytes32 internal constant INVOICE = keccak256("split-invoice-1");

    function setUp() public {
        payer = vm.addr(PAYER_PK);
        vm.warp(1_700_000_000); // stable block.timestamp for event assertions

        router = new RSendsSplitRouter();
        token = new MockERC20Permit();
        token.mint(payer, 1_000_000 * 1e6);
    }

    function _approve(uint256 amount) internal {
        vm.prank(payer);
        token.approve(address(router), amount);
    }

    function _recipients2() internal view returns (address[] memory r) {
        r = new address[](2);
        r[0] = alice;
        r[1] = bob;
    }

    function _recipients3() internal view returns (address[] memory r) {
        r = new address[](3);
        r[0] = alice;
        r[1] = bob;
        r[2] = carol;
    }

    function _bps(uint16 a, uint16 b) internal pure returns (uint16[] memory s) {
        s = new uint16[](2);
        s[0] = a;
        s[1] = b;
    }

    function _bps(uint16 a, uint16 b, uint16 c) internal pure returns (uint16[] memory s) {
        s = new uint16[](3);
        s[0] = a;
        s[1] = b;
        s[2] = c;
    }

    /*//////////////////// paySplit: happy paths ////////////////////*/

    function test_paySplit_happyPath_transfersAndEmits() public {
        uint256 total = 100_000_000; // 100.000000 (divides exactly by 5000/3000/2000)
        _approve(total);

        uint256[] memory expectedAmounts = new uint256[](3);
        expectedAmounts[0] = 50_000_000;
        expectedAmounts[1] = 30_000_000;
        expectedAmounts[2] = 20_000_000;

        vm.expectEmit(true, true, false, true, address(router));
        emit SplitPaymentMade(
            INVOICE, payer, address(token), total, _recipients3(), expectedAmounts, block.timestamp
        );

        vm.prank(payer);
        router.paySplit(INVOICE, address(token), total, _recipients3(), _bps(5000, 3000, 2000));

        assertEq(token.balanceOf(alice), 50_000_000);
        assertEq(token.balanceOf(bob), 30_000_000);
        assertEq(token.balanceOf(carol), 20_000_000);
        assertEq(token.balanceOf(address(router)), 0); // non-custodial: router holds nothing
    }

    /// Rounding dust goes to recipient[0] (the primary), never to the router.
    function test_paySplit_remainderToFirstRecipient() public {
        uint256 total = 101; // 101 * 3333 / 10000 = 33 (floor) per first two, 101*3334/10000 = 33
        _approve(total);

        vm.prank(payer);
        router.paySplit(INVOICE, address(token), total, _recipients3(), _bps(3333, 3333, 3334));

        // floors: 33 + 33 + 33 = 99, remainder 2 → primary gets 33 + 2 = 35
        assertEq(token.balanceOf(alice), 35);
        assertEq(token.balanceOf(bob), 33);
        assertEq(token.balanceOf(carol), 33);
        assertEq(token.balanceOf(address(router)), 0); // conservation: nothing stranded
    }

    function test_paySplit_maxRecipients20() public {
        uint256 n = 20;
        address[] memory rcpts = new address[](n);
        uint16[] memory bps = new uint16[](n);
        for (uint256 i = 0; i < n; i++) {
            rcpts[i] = makeAddr(string(abi.encodePacked("r", vm.toString(i))));
            bps[i] = 500; // 20 * 500 = 10000
        }
        uint256 total = 20_000_000;
        _approve(total);

        vm.prank(payer);
        router.paySplit(INVOICE, address(token), total, rcpts, bps);

        for (uint256 i = 0; i < n; i++) {
            assertEq(token.balanceOf(rcpts[i]), 1_000_000);
        }
        assertEq(token.balanceOf(address(router)), 0);
    }

    /*//////////////////// paySplit: BPS-exact invariant ////////////////////*/

    function test_paySplit_revert_bpsSumBelow10000() public {
        _approve(type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(BpsSumNot10000.selector);
        router.paySplit(INVOICE, address(token), 1_000_000, _recipients2(), _bps(5000, 4999));
    }

    function test_paySplit_revert_bpsSumAbove10000() public {
        _approve(type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(BpsSumNot10000.selector);
        router.paySplit(INVOICE, address(token), 1_000_000, _recipients2(), _bps(5000, 5001));
    }

    /*//////////////////// paySplit: shape reverts ////////////////////*/

    function test_paySplit_revert_lengthMismatch() public {
        _approve(type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(LengthMismatch.selector);
        router.paySplit(INVOICE, address(token), 1_000_000, _recipients3(), _bps(5000, 5000));
    }

    function test_paySplit_revert_singleRecipient() public {
        address[] memory one = new address[](1);
        one[0] = alice;
        uint16[] memory bps = new uint16[](1);
        bps[0] = 10000;
        _approve(type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(BadRecipientCount.selector);
        router.paySplit(INVOICE, address(token), 1_000_000, one, bps);
    }

    function test_paySplit_revert_tooManyRecipients() public {
        uint256 n = 21;
        address[] memory rcpts = new address[](n);
        uint16[] memory bps = new uint16[](n);
        for (uint256 i = 0; i < n; i++) {
            rcpts[i] = makeAddr(string(abi.encodePacked("x", vm.toString(i))));
            bps[i] = i == 0 ? 10000 - uint16((n - 1) * 476) : 476; // sums to 10000
        }
        _approve(type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(BadRecipientCount.selector);
        router.paySplit(INVOICE, address(token), 1_000_000, rcpts, bps);
    }

    function test_paySplit_revert_zeroRecipient() public {
        address[] memory rcpts = _recipients2();
        rcpts[1] = address(0);
        _approve(type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(ZeroRecipient.selector);
        router.paySplit(INVOICE, address(token), 1_000_000, rcpts, _bps(5000, 5000));
    }

    function test_paySplit_revert_zeroBps() public {
        _approve(type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(ZeroBps.selector);
        router.paySplit(INVOICE, address(token), 1_000_000, _recipients2(), _bps(10000, 0));
    }

    function test_paySplit_revert_zeroAmount() public {
        _approve(type(uint256).max);
        vm.prank(payer);
        vm.expectRevert(ZeroAmount.selector);
        router.paySplit(INVOICE, address(token), 0, _recipients2(), _bps(5000, 5000));
    }

    function test_paySplit_revert_zeroToken() public {
        vm.prank(payer);
        vm.expectRevert(ZeroToken.selector);
        router.paySplit(INVOICE, address(0), 1_000_000, _recipients2(), _bps(5000, 5000));
    }

    /*//////////////////// paySplit: atomicity ////////////////////*/

    /// One leg's transfer failing (blocklisted recipient) reverts the WHOLE split:
    /// no partial settlement can ever exist on-chain.
    function test_paySplit_atomicAllOrNothing_erc20() public {
        MockBlocklistToken blk = new MockBlocklistToken();
        blk.mint(payer, 1_000_000);
        vm.prank(payer);
        blk.approve(address(router), type(uint256).max);

        blk.setBlocked(bob, true); // second leg cannot receive

        vm.prank(payer);
        vm.expectRevert("recipient blocked");
        router.paySplit(INVOICE, address(blk), 1_000_000, _recipients2(), _bps(5000, 5000));

        // nothing moved — not even the first (unblocked) leg
        assertEq(blk.balanceOf(alice), 0);
        assertEq(blk.balanceOf(bob), 0);
        assertEq(blk.balanceOf(payer), 1_000_000);
    }

    /*//////////////////// paySplit: token compatibility ////////////////////*/

    function test_paySplit_usdtStyleNoReturnValue() public {
        MockUSDTNoReturn usdt = new MockUSDTNoReturn();
        usdt.mint(payer, 1_000_000);
        vm.prank(payer);
        usdt.approve(address(router), 1_000_000);

        vm.prank(payer);
        router.paySplit(INVOICE, address(usdt), 1_000_000, _recipients2(), _bps(7000, 3000));

        assertEq(usdt.balanceOf(alice), 700_000);
        assertEq(usdt.balanceOf(bob), 300_000);
    }

    /*//////////////////// paySplitWithPermit ////////////////////*/

    function _signPermit(uint256 value, uint256 deadline) internal view returns (uint8 v, bytes32 r, bytes32 s) {
        bytes32 permitTypehash =
            keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)");
        bytes32 structHash = keccak256(
            abi.encode(permitTypehash, payer, address(router), value, token.nonces(payer), deadline)
        );
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", token.DOMAIN_SEPARATOR(), structHash));
        (v, r, s) = vm.sign(PAYER_PK, digest);
    }

    function test_paySplitWithPermit_happyPath() public {
        uint256 total = 100_000_000;
        uint256 deadline = block.timestamp + 1 hours;
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(total, deadline);

        // no prior approve: the permit grants the allowance in the same tx
        vm.prank(payer);
        router.paySplitWithPermit(
            INVOICE, address(token), total, _recipients2(), _bps(6000, 4000), deadline, v, r, s
        );

        assertEq(token.balanceOf(alice), 60_000_000);
        assertEq(token.balanceOf(bob), 40_000_000);
        assertEq(token.balanceOf(address(router)), 0);
    }

    /// Front-run resilience: an allowance already exists; a useless/expired permit is swallowed
    /// and the split still succeeds.
    function test_paySplitWithPermit_frontRun_existingAllowanceSucceeds() public {
        uint256 total = 100_000_000;
        _approve(total); // allowance already in place

        uint256 deadline = block.timestamp - 1; // expired — must be swallowed
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(total, deadline);

        vm.prank(payer);
        router.paySplitWithPermit(
            INVOICE, address(token), total, _recipients2(), _bps(6000, 4000), deadline, v, r, s
        );

        assertEq(token.balanceOf(alice), 60_000_000);
        assertEq(token.balanceOf(bob), 40_000_000);
    }

    function test_paySplitWithPermit_expiredNoAllowance_reverts() public {
        uint256 total = 100_000_000;
        uint256 deadline = block.timestamp - 1;
        (uint8 v, bytes32 r, bytes32 s) = _signPermit(total, deadline);

        // permit reverts (expired) -> swallowed -> no allowance -> transferFrom reverts
        vm.prank(payer);
        vm.expectRevert();
        router.paySplitWithPermit(
            INVOICE, address(token), total, _recipients2(), _bps(6000, 4000), deadline, v, r, s
        );

        assertEq(token.balanceOf(alice), 0);
        assertEq(token.balanceOf(bob), 0);
    }

    /*//////////////////// paySplitNative ////////////////////*/

    function _payableRecipients2() internal view returns (address payable[] memory r) {
        r = new address payable[](2);
        r[0] = payable(alice);
        r[1] = payable(bob);
    }

    function test_paySplitNative_happyPath() public {
        uint256 total = 2 ether;
        vm.deal(payer, total);

        vm.prank(payer);
        router.paySplitNative{value: total}(INVOICE, total, _payableRecipients2(), _bps(7500, 2500));

        assertEq(alice.balance, 1.5 ether);
        assertEq(bob.balance, 0.5 ether);
        assertEq(address(router).balance, 0);
    }

    function test_paySplitNative_revert_wrongValue() public {
        uint256 total = 1 ether;
        vm.deal(payer, total + 1);
        vm.prank(payer);
        vm.expectRevert(WrongNativeValue.selector);
        router.paySplitNative{value: total + 1}(INVOICE, total, _payableRecipients2(), _bps(5000, 5000));
    }

    function test_paySplitNative_revert_bpsSumNot10000() public {
        uint256 total = 1 ether;
        vm.deal(payer, total);
        vm.prank(payer);
        vm.expectRevert(BpsSumNot10000.selector);
        router.paySplitNative{value: total}(INVOICE, total, _payableRecipients2(), _bps(5000, 4999));
    }

    /// One native leg rejecting reverts the WHOLE split — all-or-nothing.
    function test_paySplitNative_atomicAllOrNothing() public {
        RejectingRecipient bad = new RejectingRecipient();
        address payable[] memory rcpts = new address payable[](2);
        rcpts[0] = payable(alice);
        rcpts[1] = payable(address(bad));

        uint256 total = 1 ether;
        vm.deal(payer, total);
        uint256 aliceBefore = alice.balance;

        vm.prank(payer);
        vm.expectRevert(NativeTransferFailed.selector);
        router.paySplitNative{value: total}(INVOICE, total, rcpts, _bps(5000, 5000));

        assertEq(alice.balance, aliceBefore); // first leg rolled back too
        assertEq(address(router).balance, 0);
    }

    /// Reentrancy: malicious recipient re-enters paySplitNative on receive(); the re-entry is
    /// rejected by the guard, yet the outer split completes and every leg lands.
    function test_paySplitNative_reentrancyBlocked_outerCompletes() public {
        ReentrantRecipient evil = new ReentrantRecipient(router);
        address payable[] memory rcpts = new address payable[](2);
        rcpts[0] = payable(address(evil));
        rcpts[1] = payable(bob);

        uint256 total = 1 ether;
        vm.deal(payer, total);

        vm.prank(payer);
        router.paySplitNative{value: total}(INVOICE, total, rcpts, _bps(5000, 5000));

        assertTrue(evil.reentryAttempted());
        assertTrue(evil.reentryReverted());
        assertFalse(evil.reentrySucceeded());
        assertEq(address(evil).balance, 0.5 ether);
        assertEq(bob.balance, 0.5 ether);
        assertEq(address(router).balance, 0);
    }

    /*//////////////////// fuzz: conservation ////////////////////*/

    /// For ANY amount and ANY 2-way bps split, every unit of the payer's total lands with a
    /// recipient — never with the router, never burned to rounding.
    function testFuzz_paySplit_conservation(uint256 total, uint16 bpsFirst) public {
        total = bound(total, 1, 1_000_000 * 1e6);
        bpsFirst = uint16(bound(bpsFirst, 1, 9999));
        uint16[] memory bps = _bps(bpsFirst, 10000 - bpsFirst);

        token.mint(payer, total); // ensure funds on top of setUp mint
        _approve(total);

        uint256 aliceBefore = token.balanceOf(alice);
        uint256 bobBefore = token.balanceOf(bob);

        vm.prank(payer);
        router.paySplit(INVOICE, address(token), total, _recipients2(), bps);

        assertEq(
            (token.balanceOf(alice) - aliceBefore) + (token.balanceOf(bob) - bobBefore),
            total
        );
        assertEq(token.balanceOf(address(router)), 0);
        // primary carries the remainder: its share is >= the exact floor
        assertGe(token.balanceOf(alice) - aliceBefore, (total * bpsFirst) / 10000);
    }
}
