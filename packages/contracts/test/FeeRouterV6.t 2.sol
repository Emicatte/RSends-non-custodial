// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/FeeRouterV6.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";

// ═══════════════════════════════════════════════════════════════════
//  Mocks — same minimal-IERC20 pattern as V5 tests, with configurable
//  decimals (6 for realistic USDT/USDC semantics).
// ═══════════════════════════════════════════════════════════════════

contract MockERC20V6 is IERC20 {
    string  public name;
    string  public symbol;
    uint8   public decimals;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    constructor(string memory _name, string memory _symbol, uint8 _decimals) {
        name     = _name;
        symbol   = _symbol;
        decimals = _decimals;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply   += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to]         += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (allowance[from][msg.sender] != type(uint256).max) {
            allowance[from][msg.sender] -= amount;
        }
        balanceOf[from] -= amount;
        balanceOf[to]   += amount;
        return true;
    }
}

contract MockWETHV6 {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function deposit() external payable { balanceOf[msg.sender] += msg.value; }
    function withdraw(uint256 a) external { balanceOf[msg.sender] -= a; payable(msg.sender).transfer(a); }
    function approve(address s, uint256 a) external returns (bool) { allowance[msg.sender][s] = a; return true; }
    function transfer(address to, uint256 a) external returns (bool) {
        balanceOf[msg.sender] -= a; balanceOf[to] += a; return true;
    }
    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        if (allowance[f][msg.sender] != type(uint256).max) allowance[f][msg.sender] -= a;
        balanceOf[f] -= a; balanceOf[t] += a; return true;
    }
    receive() external payable { balanceOf[msg.sender] += msg.value; }
}

contract MockPermit2V6 {
    function permitTransferFrom(
        ISignatureTransfer.PermitTransferFrom memory,
        ISignatureTransfer.SignatureTransferDetails memory,
        address,
        bytes memory
    ) external pure {}
}

contract MockSwapRouterV6 {
    IERC20 public tokenOut;
    function setTokenOut(address _t) external { tokenOut = IERC20(_t); }
    function exactInputSingle(ISwapRouter.ExactInputSingleParams calldata params)
        external payable returns (uint256)
    {
        IERC20(params.tokenIn).transferFrom(msg.sender, address(this), params.amountIn);
        tokenOut.transfer(params.recipient, params.amountIn);
        return params.amountIn;
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Main test contract
// ═══════════════════════════════════════════════════════════════════
contract FeeRouterV6Test is Test {
    FeeRouterV6      public router;
    MockERC20V6      public usdc;      // 6 decimals — user-facing token
    MockERC20V6      public usdt;      // 6 decimals — fee token (NOT in allowedTokens)
    MockWETHV6       public weth;
    MockPermit2V6    public permit2;
    MockSwapRouterV6 public swapRouter;

    // 3 oracle signers for 2-of-3 multi-sig (same convention as V5 tests)
    uint256 constant ORACLE_PK1 = 0xA11CE;
    uint256 constant ORACLE_PK2 = 0xB0B;
    uint256 constant ORACLE_PK3 = 0xCAFE;
    address oracle1;
    address oracle2;
    address oracle3;

    address owner     = makeAddr("owner");
    address treasury  = makeAddr("treasury");
    address sender_   = makeAddr("sender");
    address recipient = makeAddr("recipient");

    uint256 constant DEFAULT_FEE = 10_000;  // 0.01 USDT @ 6 decimals

    bytes32 constant ORACLE_TYPEHASH = keccak256(
        "OracleApproval(address sender,address recipient,"
        "address tokenIn,address tokenOut,uint256 amountIn,"
        "bytes32 nonce,uint256 deadline)"
    );

    function setUp() public {
        oracle1 = vm.addr(ORACLE_PK1);
        oracle2 = vm.addr(ORACLE_PK2);
        oracle3 = vm.addr(ORACLE_PK3);

        permit2    = new MockPermit2V6();
        weth       = new MockWETHV6();
        swapRouter = new MockSwapRouterV6();
        usdc       = new MockERC20V6("USD Coin", "USDC", 6);
        usdt       = new MockERC20V6("Tether",   "USDT", 6);

        address[] memory signers = _sortedSigners();

        router = new FeeRouterV6(
            address(permit2),
            treasury,
            signers,
            2,                  // threshold = 2-of-3
            address(swapRouter),
            address(weth),
            address(usdt),      // USDT_TOKEN (fee token)
            owner
        );

        // USDT is intentionally NOT added to allowedTokens — it is the fee
        // token, accessed only via the _collectFlatFee path, not by callers.
        vm.startPrank(owner);
        router.setTokenAllowed(address(usdc), true);
        router.setTokenAllowed(address(weth), true);
        vm.stopPrank();

        vm.deal(sender_,   1000 ether);
        usdc.mint(sender_, 1_000_000e6);
        usdt.mint(sender_, 1_000_000e6);

        vm.startPrank(sender_);
        usdc.approve(address(router), type(uint256).max);
        usdt.approve(address(router), type(uint256).max);
        vm.stopPrank();
    }

    // ── Helpers (copied from V5 test) ─────────────────────────────────────

    function _sortedSigners() internal view returns (address[] memory) {
        address[] memory s = new address[](3);
        s[0] = oracle1;
        s[1] = oracle2;
        s[2] = oracle3;
        for (uint256 i = 0; i < 3; i++) {
            for (uint256 j = i + 1; j < 3; j++) {
                if (s[i] > s[j]) {
                    (s[i], s[j]) = (s[j], s[i]);
                }
            }
        }
        return s;
    }

    function _signOracle(
        uint256 pk,
        address _sender,
        address _recipient,
        address _tokenIn,
        address _tokenOut,
        uint256 _amountIn,
        bytes32 _nonce,
        uint256 _deadline
    ) internal view returns (bytes memory) {
        bytes32 domainSep = router.domainSeparator();
        bytes32 structHash = keccak256(abi.encode(
            ORACLE_TYPEHASH,
            _sender, _recipient, _tokenIn, _tokenOut, _amountIn, _nonce, _deadline
        ));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", domainSep, structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, digest);
        return abi.encodePacked(r, s, v);
    }

    function _signMulti(
        uint256[] memory pks,
        address _sender,
        address _recipient,
        address _tokenIn,
        address _tokenOut,
        uint256 _amountIn,
        bytes32 _nonce,
        uint256 _deadline
    ) internal view returns (bytes[] memory) {
        bytes[] memory sigs = new bytes[](pks.length);
        address[] memory addrs = new address[](pks.length);

        for (uint256 i = 0; i < pks.length; i++) {
            sigs[i] = _signOracle(pks[i], _sender, _recipient, _tokenIn, _tokenOut, _amountIn, _nonce, _deadline);
            addrs[i] = vm.addr(pks[i]);
        }

        for (uint256 i = 0; i < pks.length; i++) {
            for (uint256 j = i + 1; j < pks.length; j++) {
                if (addrs[i] > addrs[j]) {
                    (addrs[i], addrs[j]) = (addrs[j], addrs[i]);
                    (sigs[i], sigs[j]) = (sigs[j], sigs[i]);
                }
            }
        }

        return sigs;
    }

    function _sign2of3(
        address _sender,
        address _recipient,
        address _tokenIn,
        address _tokenOut,
        uint256 _amountIn,
        bytes32 _nonce,
        uint256 _deadline
    ) internal view returns (bytes[] memory) {
        uint256[] memory pks = new uint256[](2);
        pks[0] = ORACLE_PK1;
        pks[1] = ORACLE_PK2;
        return _signMulti(pks, _sender, _recipient, _tokenIn, _tokenOut, _amountIn, _nonce, _deadline);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  1. test_flatFee_USDC_transfer
    //     Recipient receives full 1000 USDC; treasury receives 0.01 USDT
    //     from sender separately.
    // ═══════════════════════════════════════════════════════════════════
    function test_flatFee_USDC_transfer() public {
        uint256 amount   = 1000e6;                       // 1000 USDC (6 dec)
        bytes32 nonce    = keccak256("v6-usdc");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = _sign2of3(
            sender_, recipient, address(usdc), address(usdc), amount, nonce, deadline
        );

        uint256 recipientUsdcBefore  = usdc.balanceOf(recipient);
        uint256 treasuryUsdtBefore   = usdt.balanceOf(treasury);
        uint256 senderUsdtBefore     = usdt.balanceOf(sender_);

        // Expect the new FlatFeeCollected event
        vm.expectEmit(true, false, false, true);
        emit FeeRouterV6.FlatFeeCollected(sender_, DEFAULT_FEE, nonce);

        vm.prank(sender_);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sigs);

        assertEq(usdc.balanceOf(recipient) - recipientUsdcBefore, amount,       "recipient full amount");
        assertEq(usdt.balanceOf(treasury)  - treasuryUsdtBefore,  DEFAULT_FEE,  "treasury flat fee");
        assertEq(senderUsdtBefore - usdt.balanceOf(sender_),       DEFAULT_FEE,  "sender USDT delta");
    }

    // ═══════════════════════════════════════════════════════════════════
    //  2. test_flatFee_dustSkip
    //     amount < fixedFeeUSDT → fee silently skipped, no event emitted.
    // ═══════════════════════════════════════════════════════════════════
    function test_flatFee_dustSkip() public {
        uint256 amount   = 5_000;                        // below fixedFeeUSDT (10_000)
        bytes32 nonce    = keccak256("v6-dust");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = _sign2of3(
            sender_, recipient, address(usdc), address(usdc), amount, nonce, deadline
        );

        uint256 recipientUsdcBefore = usdc.balanceOf(recipient);
        uint256 treasuryUsdtBefore  = usdt.balanceOf(treasury);
        uint256 senderUsdtBefore    = usdt.balanceOf(sender_);

        vm.recordLogs();

        vm.prank(sender_);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sigs);

        assertEq(usdc.balanceOf(recipient) - recipientUsdcBefore, amount, "recipient gets dust amount");
        assertEq(usdt.balanceOf(treasury), treasuryUsdtBefore,             "treasury USDT unchanged");
        assertEq(usdt.balanceOf(sender_),  senderUsdtBefore,               "sender USDT unchanged");

        // Verify FlatFeeCollected was NOT emitted
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bytes32 flatFeeTopic = keccak256("FlatFeeCollected(address,uint256,bytes32)");
        for (uint256 i = 0; i < logs.length; i++) {
            assertTrue(
                logs[i].topics.length == 0 || logs[i].topics[0] != flatFeeTopic,
                "FlatFeeCollected should not be emitted on dust skip"
            );
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    //  3. test_flatFee_ETH_alwaysCharged
    //     Tiny ETH transfer (0.001 ETH) still pays the flat USDT fee
    //     (no dust check on ETH paths).
    // ═══════════════════════════════════════════════════════════════════
    function test_flatFee_ETH_alwaysCharged() public {
        uint256 amount   = 0.001 ether;
        bytes32 nonce    = keccak256("v6-eth-tiny");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = _sign2of3(
            sender_, recipient, address(0), address(0), amount, nonce, deadline
        );

        uint256 recipientEthBefore = recipient.balance;
        uint256 treasuryUsdtBefore = usdt.balanceOf(treasury);

        vm.prank(sender_);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);

        assertEq(recipient.balance - recipientEthBefore,        amount,       "recipient full ETH");
        assertEq(usdt.balanceOf(treasury) - treasuryUsdtBefore, DEFAULT_FEE,  "fee charged despite tiny ETH");
    }

    // ═══════════════════════════════════════════════════════════════════
    //  4. test_setFixedFeeUSDT_onlyOwner
    //     Owner can update the fee; non-owners revert.
    // ═══════════════════════════════════════════════════════════════════
    function test_setFixedFeeUSDT_onlyOwner() public {
        // Owner success path
        vm.expectEmit(false, false, false, true);
        emit FeeRouterV6.FixedFeeUpdated(DEFAULT_FEE, 20_000);

        vm.prank(owner);
        router.setFixedFeeUSDT(20_000);

        assertEq(router.getFlatFee(), 20_000, "fee updated");

        // Non-owner revert path
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, sender_));
        vm.prank(sender_);
        router.setFixedFeeUSDT(99_999);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  5. test_feeZero_noTransfer
    //     With fixedFeeUSDT=0, no USDT pull and no FlatFeeCollected event.
    // ═══════════════════════════════════════════════════════════════════
    function test_feeZero_noTransfer() public {
        vm.prank(owner);
        router.setFixedFeeUSDT(0);

        uint256 amount   = 1000e6;
        bytes32 nonce    = keccak256("v6-fee-zero");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = _sign2of3(
            sender_, recipient, address(usdc), address(usdc), amount, nonce, deadline
        );

        uint256 recipientUsdcBefore = usdc.balanceOf(recipient);
        uint256 treasuryUsdtBefore  = usdt.balanceOf(treasury);

        vm.recordLogs();

        vm.prank(sender_);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sigs);

        assertEq(usdc.balanceOf(recipient) - recipientUsdcBefore, amount, "recipient gets full amount");
        assertEq(usdt.balanceOf(treasury), treasuryUsdtBefore,             "treasury USDT unchanged");

        Vm.Log[] memory logs = vm.getRecordedLogs();
        bytes32 flatFeeTopic = keccak256("FlatFeeCollected(address,uint256,bytes32)");
        for (uint256 i = 0; i < logs.length; i++) {
            assertTrue(
                logs[i].topics.length == 0 || logs[i].topics[0] != flatFeeTopic,
                "FlatFeeCollected should not be emitted when fee is 0"
            );
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    //  6. test_insufficientUSDTAllowance_reverts
    //     If sender hasn't approved USDT, the whole tx reverts atomically
    //     (recipient receives nothing).
    // ═══════════════════════════════════════════════════════════════════
    function test_insufficientUSDTAllowance_reverts() public {
        // Revoke USDT approval; USDC approval stays at max
        vm.prank(sender_);
        usdt.approve(address(router), 0);

        uint256 amount   = 1000e6;                       // above dust
        bytes32 nonce    = keccak256("v6-no-usdt-allow");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = _sign2of3(
            sender_, recipient, address(usdc), address(usdc), amount, nonce, deadline
        );

        uint256 recipientUsdcBefore = usdc.balanceOf(recipient);
        uint256 treasuryUsdtBefore  = usdt.balanceOf(treasury);

        vm.prank(sender_);
        vm.expectRevert();   // accepts SafeERC20FailedOperation or any underflow revert
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sigs);

        // Atomic revert: nothing moved
        assertEq(usdc.balanceOf(recipient), recipientUsdcBefore, "recipient unchanged");
        assertEq(usdt.balanceOf(treasury),  treasuryUsdtBefore,  "treasury unchanged");
    }

    // ═══════════════════════════════════════════════════════════════════
    //  M10 — circuit breaker (Pausable) + two-step ownership (Ownable2Step)
    // ═══════════════════════════════════════════════════════════════════

    // Builds valid 2-of-3 oracle sigs for a standard 1000 USDC transferWithOracle.
    function _validUsdcTransfer(bytes32 nonce)
        internal
        view
        returns (uint256 amount, uint256 deadline, bytes[] memory sigs)
    {
        amount   = 1000e6;
        deadline = block.timestamp + 1 hours;
        sigs = _sign2of3(sender_, recipient, address(usdc), address(usdc), amount, nonce, deadline);
    }

    function test_M10_pauseBlocksTransfer() public {
        bytes32 nonce = keccak256("m10-pause");
        (uint256 amount, uint256 deadline, bytes[] memory sigs) = _validUsdcTransfer(nonce);

        vm.prank(owner);
        router.pause();

        // whenNotPaused reverts BEFORE the (otherwise-valid) body runs.
        vm.prank(sender_);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sigs);
    }

    function test_M10_unpauseRestoresTransfer() public {
        bytes32 nonce = keccak256("m10-unpause");
        (uint256 amount, uint256 deadline, bytes[] memory sigs) = _validUsdcTransfer(nonce);

        vm.prank(owner);
        router.pause();
        vm.prank(owner);
        router.unpause();

        uint256 recipientBefore = usdc.balanceOf(recipient);

        vm.prank(sender_);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sigs);

        // Unpause fully restores the rail: the otherwise-identical transfer goes through.
        assertEq(usdc.balanceOf(recipient) - recipientBefore, amount, "transfer works after unpause");
        assertFalse(router.paused(), "router unpaused");
    }

    function test_M10_pausedStateToggles() public {
        assertFalse(router.paused(), "starts unpaused");
        vm.prank(owner);
        router.pause();
        assertTrue(router.paused(), "paused after pause()");
        vm.prank(owner);
        router.unpause();
        assertFalse(router.paused(), "unpaused after unpause()");
    }

    function test_M10_pauseOnlyOwner() public {
        vm.prank(sender_);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, sender_));
        router.pause();
    }

    function test_M10_unpauseOnlyOwner() public {
        vm.prank(owner);
        router.pause();

        vm.prank(sender_);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, sender_));
        router.unpause();
    }

    function test_M10_ownable2Step_transfer() public {
        address newOwner = makeAddr("newOwner");

        // Step 1: transfer does NOT immediately change the owner.
        vm.prank(owner);
        router.transferOwnership(newOwner);
        assertEq(router.owner(), owner, "owner unchanged until accept");
        assertEq(router.pendingOwner(), newOwner, "pending owner set");

        // Step 2: the pending owner accepts → ownership moves.
        vm.prank(newOwner);
        router.acceptOwnership();
        assertEq(router.owner(), newOwner, "owner updated after accept");
        assertEq(router.pendingOwner(), address(0), "pending cleared");
    }

    function test_M10_ownable2Step_onlyPendingAccepts() public {
        address newOwner = makeAddr("newOwner");
        vm.prank(owner);
        router.transferOwnership(newOwner);

        // A non-pending address cannot hijack the handover.
        vm.prank(sender_);
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, sender_));
        router.acceptOwnership();
    }
}
