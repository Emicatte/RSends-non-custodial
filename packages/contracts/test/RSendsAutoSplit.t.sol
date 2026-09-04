// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import "../src/RSendsAutoSplit.sol"; // brings in RSendsAutoSplit + the file-level errors

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/*//////////////////////////////////////////////////////////////
                              MOCKS
//////////////////////////////////////////////////////////////*/

/// 6-decimal USDC look-alike (matches the Base USDC the contract targets).
contract MockUSDC is ERC20 {
    constructor() ERC20("Mock USDC", "mUSDC") {}
    function decimals() public pure override returns (uint8) { return 6; }
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
/// Used to prove a distribution is all-or-nothing when ONE leg cannot receive.
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

/// Malicious token: re-enters executeSplit from inside the first leg's transfer,
/// swallowing the revert so the outer execution can still complete.
contract ReentrantToken is ERC20 {
    RSendsAutoSplit public autoSplit;
    address public merchant;
    bool public reentryAttempted;
    bool public reentryReverted;
    bool public reentrySucceeded;

    constructor() ERC20("Reentrant USD", "rUSD") {}
    function mint(address to, uint256 amount) external { _mint(to, amount); }
    function arm(RSendsAutoSplit a, address m) external { autoSplit = a; merchant = m; }

    function _update(address from, address to, uint256 value) internal override {
        super._update(from, to, value);
        if (address(autoSplit) != address(0) && !reentryAttempted && from == merchant) {
            reentryAttempted = true;
            try autoSplit.executeSplit(merchant, address(this)) {
                reentrySucceeded = true;
            } catch {
                reentryReverted = true;
            }
        }
    }
}

/*//////////////////////////////////////////////////////////////
                              TESTS
//////////////////////////////////////////////////////////////*/

contract RSendsAutoSplitTest is Test {
    // mirrors of the contract events for expectEmit
    event PolicySet(
        address indexed merchant, address indexed token,
        address[] recipients, uint16[] bps, uint256 minAmount
    );
    event PolicyCleared(address indexed merchant, address indexed token);
    event SplitExecuted(
        address indexed merchant, address indexed token, address indexed caller,
        uint256 totalAmount, address[] recipients, uint256[] amounts, uint256 blockTimestamp
    );

    RSendsAutoSplit autoSplit;
    MockUSDC usdc;

    address internal merchant = makeAddr("merchant");
    address internal keeper   = makeAddr("keeper"); // unprivileged executor
    address internal mallory  = makeAddr("mallory");
    address internal alice    = makeAddr("alice");
    address internal bob      = makeAddr("bob");
    address internal carol    = makeAddr("carol"); // last position = gets remainder

    function setUp() public {
        vm.warp(1_700_000_000); // stable block.timestamp for event assertions
        autoSplit = new RSendsAutoSplit();
        usdc = new MockUSDC();
    }

    /*//////////////////// helpers ////////////////////*/

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

    /// Registers the standard 3-way policy (50/30/20) on `usdc` for `merchant`.
    function _setPolicy3(uint256 minAmount) internal {
        vm.prank(merchant);
        autoSplit.setPolicy(address(usdc), _recipients3(), _bps(5000, 3000, 2000), minAmount);
    }

    function _fundAndApproveMax(uint256 amount) internal {
        usdc.mint(merchant, amount);
        vm.prank(merchant);
        usdc.approve(address(autoSplit), type(uint256).max);
    }

    /*//////////////////// setPolicy: shape reverts ////////////////////*/

    function test_setPolicy_revert_bpsSumNot10000() public {
        vm.prank(merchant);
        vm.expectRevert(BpsSumNot10000.selector);
        autoSplit.setPolicy(address(usdc), _recipients2(), _bps(5000, 4999), 0);

        vm.prank(merchant);
        vm.expectRevert(BpsSumNot10000.selector);
        autoSplit.setPolicy(address(usdc), _recipients2(), _bps(5000, 5001), 0);
    }

    function test_setPolicy_revert_recipientCountBelow2() public {
        address[] memory one = new address[](1);
        one[0] = alice;
        uint16[] memory bps = new uint16[](1);
        bps[0] = 10000;
        vm.prank(merchant);
        vm.expectRevert(BadRecipientCount.selector);
        autoSplit.setPolicy(address(usdc), one, bps, 0);
    }

    function test_setPolicy_revert_recipientCountAbove10() public {
        uint256 n = 11;
        address[] memory rcpts = new address[](n);
        uint16[] memory bps = new uint16[](n);
        for (uint256 i = 0; i < n; i++) {
            rcpts[i] = makeAddr(string(abi.encodePacked("r", vm.toString(i))));
            bps[i] = i == 0 ? 910 : 909; // 910 + 10 * 909 = 10000
        }
        vm.prank(merchant);
        vm.expectRevert(BadRecipientCount.selector);
        autoSplit.setPolicy(address(usdc), rcpts, bps, 0);
    }

    function test_setPolicy_revert_duplicateRecipient() public {
        address[] memory rcpts = new address[](2);
        rcpts[0] = alice;
        rcpts[1] = alice;
        vm.prank(merchant);
        vm.expectRevert(DuplicateRecipient.selector);
        autoSplit.setPolicy(address(usdc), rcpts, _bps(5000, 5000), 0);
    }

    function test_setPolicy_revert_zeroRecipient() public {
        address[] memory rcpts = _recipients2();
        rcpts[1] = address(0);
        vm.prank(merchant);
        vm.expectRevert(ZeroRecipient.selector);
        autoSplit.setPolicy(address(usdc), rcpts, _bps(5000, 5000), 0);
    }

    /*//////////// setPolicy: the merchant is not a valid recipient ////////////

    A leg paying the merchant is a self-transfer at execution time: balanceOf
    goes down by X and straight back up by X, so the wallet does NOT land at
    zero and the residue equals that leg. Because executeSplit is
    permissionless and has no cooldown, the residue is then re-split by every
    subsequent call — the merchant's own share erodes to dust in favour of the
    other recipients, under the ordinary keeper cadence and with no attacker
    required. Rejected at configuration time, which is the only place it can be
    rejected: the policy is what is wrong, not the execution.
    //////////////////////////////////////////////////////////////////////////*/

    function test_setPolicy_revert_selfRecipient_firstPosition() public {
        address[] memory rcpts = _recipients3();
        rcpts[0] = merchant;
        vm.prank(merchant);
        vm.expectRevert(SelfRecipient.selector);
        autoSplit.setPolicy(address(usdc), rcpts, _bps(5000, 3000, 2000), 0);
    }

    function test_setPolicy_revert_selfRecipient_middlePosition() public {
        address[] memory rcpts = _recipients3();
        rcpts[1] = merchant;
        vm.prank(merchant);
        vm.expectRevert(SelfRecipient.selector);
        autoSplit.setPolicy(address(usdc), rcpts, _bps(5000, 3000, 2000), 0);
    }

    /// Last position is the sharpest case: the remainder rule hands this leg
    /// `total - allocated`, so the merchant would retain the rounding dust too.
    function test_setPolicy_revert_selfRecipient_lastPosition() public {
        address[] memory rcpts = _recipients3();
        rcpts[2] = merchant;
        vm.prank(merchant);
        vm.expectRevert(SelfRecipient.selector);
        autoSplit.setPolicy(address(usdc), rcpts, _bps(5000, 3000, 2000), 0);
    }

    /// The revert must NAME the real problem. DuplicateRecipient would be
    /// wrong — nothing is duplicated — and would send whoever hits it looking
    /// for a repeated address that is not there. Asserted on the raw revert
    /// payload rather than via expectRevert, so the test states positively
    /// which selector came back AND negatively which one did not.
    function test_setPolicy_selfRecipient_revertsWithSelfRecipient_notDuplicateRecipient() public {
        address[] memory rcpts = _recipients2();
        rcpts[0] = merchant;

        vm.prank(merchant);
        (bool ok, bytes memory ret) = address(autoSplit).call(
            abi.encodeCall(
                RSendsAutoSplit.setPolicy,
                (address(usdc), rcpts, _bps(5000, 5000), 0)
            )
        );

        assertFalse(ok, "setPolicy accepted the merchant as its own recipient");
        assertEq(ret.length, 4, "expected a 4-byte custom-error selector");
        assertEq(bytes4(ret), SelfRecipient.selector);
        assertTrue(bytes4(ret) != DuplicateRecipient.selector, "mislabelled as a duplicate");
    }

    /// The merchant is only rejected for ITS OWN policy. `alice` setting a
    /// policy that pays `merchant` is ordinary and must keep working — the
    /// check is against msg.sender, not against some global address list.
    function test_setPolicy_anotherMerchantMayPayThisMerchant() public {
        address[] memory rcpts = _recipients2();
        rcpts[0] = merchant; // alice pays merchant: fine, merchant is not the caller
        rcpts[1] = bob;

        vm.prank(alice);
        autoSplit.setPolicy(address(usdc), rcpts, _bps(5000, 5000), 0);

        (address[] memory got,,) = autoSplit.getPolicy(alice, address(usdc));
        assertEq(got[0], merchant);
        assertEq(got[1], bob);
    }

    function test_setPolicy_revert_zeroToken() public {
        vm.prank(merchant);
        vm.expectRevert(ZeroToken.selector);
        autoSplit.setPolicy(address(0), _recipients2(), _bps(5000, 5000), 0);
    }

    function test_setPolicy_revert_lengthMismatch() public {
        vm.prank(merchant);
        vm.expectRevert(LengthMismatch.selector);
        autoSplit.setPolicy(address(usdc), _recipients3(), _bps(5000, 5000), 0);
    }

    function test_setPolicy_revert_zeroBpsLeg() public {
        vm.prank(merchant);
        vm.expectRevert(ZeroBps.selector);
        autoSplit.setPolicy(address(usdc), _recipients2(), _bps(10000, 0), 0);
    }

    /*//////////////////// setPolicy: storage ////////////////////*/

    function test_setPolicy_happyPath_storesAndEmits() public {
        vm.expectEmit(true, true, false, true, address(autoSplit));
        emit PolicySet(merchant, address(usdc), _recipients3(), _bps(5000, 3000, 2000), 42);

        vm.prank(merchant);
        autoSplit.setPolicy(address(usdc), _recipients3(), _bps(5000, 3000, 2000), 42);

        (address[] memory rcpts, uint16[] memory bps, uint256 minAmount) =
            autoSplit.getPolicy(merchant, address(usdc));
        assertEq(rcpts.length, 3);
        assertEq(rcpts[0], alice);
        assertEq(rcpts[1], bob);
        assertEq(rcpts[2], carol);
        assertEq(bps.length, 3);
        assertEq(bps[0], 5000);
        assertEq(bps[1], 3000);
        assertEq(bps[2], 2000);
        assertEq(minAmount, 42);
    }

    /// Overwriting must REPLACE the whole policy — including shrinking the arrays.
    function test_setPolicy_overwrite_replacesPreviousPolicy() public {
        _setPolicy3(42);

        vm.prank(merchant);
        autoSplit.setPolicy(address(usdc), _recipients2(), _bps(6000, 4000), 7);

        (address[] memory rcpts, uint16[] memory bps, uint256 minAmount) =
            autoSplit.getPolicy(merchant, address(usdc));
        assertEq(rcpts.length, 2);
        assertEq(rcpts[0], alice);
        assertEq(rcpts[1], bob);
        assertEq(bps.length, 2);
        assertEq(bps[0], 6000);
        assertEq(bps[1], 4000);
        assertEq(minAmount, 7);
    }

    /// msg.sender is the merchant key: a stranger writing a policy only ever
    /// writes their OWN slot, never another merchant's.
    function test_setPolicy_isolation_cannotWriteAnotherMerchantsPolicy() public {
        _setPolicy3(0);

        // carol, not mallory: a caller may not be its own recipient, and this
        // test is about WHOSE KEY the write lands under — not about the
        // recipient rules.
        address[] memory theirs = new address[](2);
        theirs[0] = carol;
        theirs[1] = keeper;
        vm.prank(mallory);
        autoSplit.setPolicy(address(usdc), theirs, _bps(9000, 1000), 0);

        // merchant's policy untouched
        (address[] memory rcpts, uint16[] memory bps,) = autoSplit.getPolicy(merchant, address(usdc));
        assertEq(rcpts.length, 3);
        assertEq(rcpts[0], alice);
        assertEq(bps[0], 5000);

        // mallory's write landed under mallory's own key only
        (address[] memory mRcpts,,) = autoSplit.getPolicy(mallory, address(usdc));
        assertEq(mRcpts.length, 2);
        assertEq(mRcpts[0], carol);
    }

    /*//////////////////// clearPolicy ////////////////////*/

    function test_clearPolicy_removesPolicy_andExecuteReverts() public {
        _setPolicy3(0);
        _fundAndApproveMax(1_000_000);

        vm.expectEmit(true, true, false, true, address(autoSplit));
        emit PolicyCleared(merchant, address(usdc));
        vm.prank(merchant);
        autoSplit.clearPolicy(address(usdc));

        (address[] memory rcpts,,) = autoSplit.getPolicy(merchant, address(usdc));
        assertEq(rcpts.length, 0);

        vm.prank(keeper);
        vm.expectRevert(NoPolicy.selector);
        autoSplit.executeSplit(merchant, address(usdc));
    }

    /*//////////////////// executeSplit: happy path ////////////////////*/

    function test_executeSplit_happyPath_merchantBalanceExactlyZero() public {
        _setPolicy3(0);
        uint256 total = 100_000_000; // 100.000000, divides exactly by 5000/3000/2000
        _fundAndApproveMax(total);

        uint256[] memory expectedAmounts = new uint256[](3);
        expectedAmounts[0] = 50_000_000;
        expectedAmounts[1] = 30_000_000;
        expectedAmounts[2] = 20_000_000;

        vm.expectEmit(true, true, true, true, address(autoSplit));
        emit SplitExecuted(
            merchant, address(usdc), keeper, total, _recipients3(), expectedAmounts, block.timestamp
        );

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdc));

        assertEq(usdc.balanceOf(merchant), 0); // the dedicated wallet lands at exactly zero
        assertEq(usdc.balanceOf(alice), 50_000_000);
        assertEq(usdc.balanceOf(bob), 30_000_000);
        assertEq(usdc.balanceOf(carol), 20_000_000);
        assertEq(usdc.balanceOf(address(autoSplit)), 0); // non-custodial: contract holds nothing
    }

    /// Rounding dust goes to the LAST recipient (amount - sum(previous floors)),
    /// which is what lands the merchant balance at exactly zero.
    function test_executeSplit_remainderGoesToLastRecipient() public {
        _setPolicy3(0);
        uint256 total = 101; // does not divide evenly by 5000/3000/2000
        _fundAndApproveMax(total);

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdc));

        // floor(101*0.5)=50, floor(101*0.3)=30, last = 101 - 80 = 21 (exact floor would be 20)
        assertEq(usdc.balanceOf(alice), 50);
        assertEq(usdc.balanceOf(bob), 30);
        assertEq(usdc.balanceOf(carol), 21);
        assertEq(usdc.balanceOf(merchant), 0);
    }

    /// A caller with no privilege whatsoever can trigger a valid split.
    function test_executeSplit_permissionless_strangerCanExecute() public {
        _setPolicy3(0);
        _fundAndApproveMax(10_000_000);

        vm.prank(mallory); // not the merchant, not a keeper the contract knows about
        autoSplit.executeSplit(merchant, address(usdc));

        assertEq(usdc.balanceOf(merchant), 0);
        assertEq(usdc.balanceOf(alice), 5_000_000);
    }

    /*//////////////////// executeSplit: amount guards ////////////////////*/

    function test_executeSplit_revert_noPolicy() public {
        _fundAndApproveMax(1_000_000);
        vm.prank(keeper);
        vm.expectRevert(NoPolicy.selector);
        autoSplit.executeSplit(merchant, address(usdc));
    }

    function test_executeSplit_revert_zeroBalance() public {
        _setPolicy3(0);
        vm.prank(merchant);
        usdc.approve(address(autoSplit), type(uint256).max); // allowance MAX, balance 0
        vm.prank(keeper);
        vm.expectRevert(ZeroAmount.selector);
        autoSplit.executeSplit(merchant, address(usdc));
    }

    function test_executeSplit_revert_belowMinAmount() public {
        _setPolicy3(1_000_000);
        _fundAndApproveMax(999_999);
        vm.prank(keeper);
        vm.expectRevert(abi.encodeWithSelector(BelowMinAmount.selector, 999_999, 1_000_000));
        autoSplit.executeSplit(merchant, address(usdc));
    }

    function test_executeSplit_minAmountBoundary_exactAmountExecutes() public {
        _setPolicy3(1_000_000);
        _fundAndApproveMax(1_000_000);
        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdc));
        assertEq(usdc.balanceOf(merchant), 0);
    }

    /// amount = min(balance, allowance): a finite allowance caps the distribution
    /// and the residue stays with the merchant (exact-zero holds only under MAX approve).
    function test_executeSplit_amountIsMinOfBalanceAndAllowance() public {
        _setPolicy3(0);
        usdc.mint(merchant, 100);
        vm.prank(merchant);
        usdc.approve(address(autoSplit), 60);

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdc));

        assertEq(usdc.balanceOf(merchant), 40); // 100 - min(100, 60)
        assertEq(usdc.balanceOf(alice), 30);    // 50% of 60
        assertEq(usdc.balanceOf(bob), 18);      // 30% of 60
        assertEq(usdc.balanceOf(carol), 12);    // remainder leg: 60 - 48
    }

    /// Unilateral revocation: approve(0) makes execution revert.
    function test_executeSplit_revert_revokedApproval() public {
        _setPolicy3(0);
        _fundAndApproveMax(1_000_000);
        vm.prank(merchant);
        usdc.approve(address(autoSplit), 0);

        vm.prank(keeper);
        vm.expectRevert(ZeroAmount.selector);
        autoSplit.executeSplit(merchant, address(usdc));
        assertEq(usdc.balanceOf(merchant), 1_000_000); // nothing moved
    }

    /// The wallet drained to zero, an immediate second execution has nothing to move.
    function test_executeSplit_secondConsecutiveExecutionReverts() public {
        _setPolicy3(0);
        _fundAndApproveMax(1_000_000);

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdc));
        assertEq(usdc.balanceOf(merchant), 0);

        vm.prank(keeper);
        vm.expectRevert(ZeroAmount.selector);
        autoSplit.executeSplit(merchant, address(usdc));
    }

    /// REGRESSION GUARD for the self-recipient finding — this is the property
    /// that self-recipient policies violated, stated directly.
    ///
    /// executeSplit is permissionless and has no cooldown, so the ONLY thing
    /// stopping anyone from re-running it and re-splitting whatever is left is
    /// that one call leaves nothing behind. When the merchant was a recipient
    /// that stopped being true: their own leg was a self-transfer, the residue
    /// survived, and each further call moved ~80% of it to the other
    /// recipients — 500/300/200 became 625/374/1 in five calls, with no
    /// attacker and no malice, just the ordinary keeper cadence.
    ///
    /// So: after one execution nothing may remain to re-split, and repeated
    /// calls must be inert rather than redistributive. If a future change makes
    /// any leg a no-op transfer (self-recipient again, a rebasing token, an
    /// early `continue` on a zero amount), THIS is what breaks.
    ///
    /// Honest note on its power: it cannot go RED for the self-recipient case
    /// any more, because setPolicy now refuses to build such a policy — the
    /// precondition is unreachable through the public API. It guards the
    /// invariant, and the setPolicy tests above guard the door.
    function test_executeSplit_oneCallLeavesNothingToReSplit_selfRecipientGuard() public {
        _setPolicy3(0);
        _fundAndApproveMax(1_000_000);

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdc));

        // One call is the whole distribution: the wallet is empty and every
        // unit is accounted for at a recipient.
        assertEq(usdc.balanceOf(merchant), 0, "residue left behind after one execution");
        assertEq(
            usdc.balanceOf(alice) + usdc.balanceOf(bob) + usdc.balanceOf(carol),
            1_000_000
        );

        uint256 aliceAfter = usdc.balanceOf(alice);
        uint256 bobAfter   = usdc.balanceOf(bob);
        uint256 carolAfter = usdc.balanceOf(carol);

        // Anyone may keep calling. Nothing may move, ever — no drift, no dust
        // fixed point that quietly keeps paying out.
        for (uint256 i; i < 3; ++i) {
            vm.prank(mallory);
            vm.expectRevert(ZeroAmount.selector);
            autoSplit.executeSplit(merchant, address(usdc));
        }

        assertEq(usdc.balanceOf(merchant), 0);
        assertEq(usdc.balanceOf(alice), aliceAfter, "a repeat execution moved funds");
        assertEq(usdc.balanceOf(bob),   bobAfter,   "a repeat execution moved funds");
        assertEq(usdc.balanceOf(carol), carolAfter, "a repeat execution moved funds");
    }

    /*//////////////////// executeSplit: atomicity ////////////////////*/

    /// One leg's transfer failing (blocklisted recipient) reverts the WHOLE
    /// distribution: no partial payout can ever exist on-chain.
    function test_executeSplit_revert_blocklistedRecipient_allOrNothing() public {
        MockBlocklistToken blk = new MockBlocklistToken();
        vm.prank(merchant);
        autoSplit.setPolicy(address(blk), _recipients2(), _bps(5000, 5000), 0);
        blk.mint(merchant, 1_000_000);
        vm.prank(merchant);
        blk.approve(address(autoSplit), type(uint256).max);

        blk.setBlocked(bob, true); // second leg cannot receive

        vm.prank(keeper);
        vm.expectRevert("recipient blocked");
        autoSplit.executeSplit(merchant, address(blk));

        // nothing moved — not even the first (unblocked) leg
        assertEq(blk.balanceOf(alice), 0);
        assertEq(blk.balanceOf(bob), 0);
        assertEq(blk.balanceOf(merchant), 1_000_000);
    }

    /// Re-entering executeSplit from inside a leg's transfer is rejected by the
    /// guard while the outer execution completes normally.
    function test_executeSplit_reentrantToken_guardHolds() public {
        ReentrantToken evil = new ReentrantToken();
        vm.prank(merchant);
        autoSplit.setPolicy(address(evil), _recipients2(), _bps(5000, 5000), 0);
        evil.mint(merchant, 1_000_000);
        vm.prank(merchant);
        evil.approve(address(autoSplit), type(uint256).max);
        evil.arm(autoSplit, merchant);

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(evil));

        assertTrue(evil.reentryAttempted());
        assertTrue(evil.reentryReverted());
        assertFalse(evil.reentrySucceeded());
        assertEq(evil.balanceOf(merchant), 0);
        assertEq(evil.balanceOf(alice), 500_000);
        assertEq(evil.balanceOf(bob), 500_000);
    }

    /*//////////////////// token compatibility ////////////////////*/

    function test_executeSplit_usdtStyleNoReturnToken() public {
        MockUSDTNoReturn usdt = new MockUSDTNoReturn();
        vm.prank(merchant);
        autoSplit.setPolicy(address(usdt), _recipients2(), _bps(7000, 3000), 0);
        usdt.mint(merchant, 1_000_000);
        vm.prank(merchant);
        usdt.approve(address(autoSplit), type(uint256).max);

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdt));

        assertEq(usdt.balanceOf(merchant), 0);
        assertEq(usdt.balanceOf(alice), 700_000);
        assertEq(usdt.balanceOf(bob), 300_000);
    }

    /*//////////////////// previewSplit ////////////////////*/

    function test_previewSplit_matchesExecution_andSharesGuards() public {
        _setPolicy3(0);
        _fundAndApproveMax(101);

        (uint256 total, uint256[] memory amounts) = autoSplit.previewSplit(merchant, address(usdc));
        assertEq(total, 101);
        assertEq(amounts.length, 3);
        assertEq(amounts[0], 50);
        assertEq(amounts[1], 30);
        assertEq(amounts[2], 21);

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdc));
        assertEq(usdc.balanceOf(alice), amounts[0]);
        assertEq(usdc.balanceOf(bob), amounts[1]);
        assertEq(usdc.balanceOf(carol), amounts[2]);

        // after the drain, preview reverts exactly like executeSplit would
        vm.expectRevert(ZeroAmount.selector);
        autoSplit.previewSplit(merchant, address(usdc));
    }

    /*//////////////////// no admin surface ////////////////////*/

    /// Regression pin (mirrors RSendsRouterV2's): no owner/pause/config selector exists.
    function test_noOwnerSurface_adminSelectorsAllRevert() public {
        bytes[] memory adminCalls = new bytes[](8);
        adminCalls[0] = abi.encodeWithSignature("owner()");
        adminCalls[1] = abi.encodeWithSignature("pendingOwner()");
        adminCalls[2] = abi.encodeWithSignature("transferOwnership(address)", address(1));
        adminCalls[3] = abi.encodeWithSignature("renounceOwnership()");
        adminCalls[4] = abi.encodeWithSignature("pause()");
        adminCalls[5] = abi.encodeWithSignature("unpause()");
        adminCalls[6] = abi.encodeWithSignature("paused()");
        adminCalls[7] = abi.encodeWithSignature(
            "setFeeConfig(address,uint256,uint256,uint256,bool)", address(usdc), 1, 1, 1, true
        );
        for (uint256 i = 0; i < adminCalls.length; i++) {
            (bool ok,) = address(autoSplit).call(adminCalls[i]);
            assertFalse(ok, "admin selector unexpectedly exists");
        }
    }

    /*//////////////////// fuzz: conservation ////////////////////*/

    /// For ANY balance and ANY 2-way bps split: every unit leaves the merchant,
    /// the merchant lands at exactly zero, and the contract holds nothing.
    function testFuzz_executeSplit_conservation(uint256 total, uint16 bpsFirst) public {
        total = bound(total, 1, 1_000_000 * 1e6);
        bpsFirst = uint16(bound(bpsFirst, 1, 9999));

        vm.prank(merchant);
        autoSplit.setPolicy(address(usdc), _recipients2(), _bps(bpsFirst, 10000 - bpsFirst), 0);
        _fundAndApproveMax(total);

        vm.prank(keeper);
        autoSplit.executeSplit(merchant, address(usdc));

        assertEq(usdc.balanceOf(merchant), 0);
        assertEq(usdc.balanceOf(alice) + usdc.balanceOf(bob), total);
        assertEq(usdc.balanceOf(address(autoSplit)), 0);
        // the last leg carries the remainder: its share is >= the exact floor
        assertGe(usdc.balanceOf(bob), (total * (10000 - bpsFirst)) / 10000);
    }
}
