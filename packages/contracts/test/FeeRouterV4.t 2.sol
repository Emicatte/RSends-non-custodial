// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/FeeRouterV4.sol";

// ═══════════════════════════════════════════════════════════════════
//  Mock contracts
// ═══════════════════════════════════════════════════════════════════

/// @dev Standard ERC20 for testing
contract MockERC20 is IERC20 {
    string  public name;
    string  public symbol;
    uint8   public decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    constructor(string memory _name, string memory _symbol) {
        name   = _name;
        symbol = _symbol;
    }

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply   += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external virtual returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to]         += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external virtual returns (bool) {
        if (allowance[from][msg.sender] != type(uint256).max) {
            allowance[from][msg.sender] -= amount;
        }
        balanceOf[from] -= amount;
        balanceOf[to]   += amount;
        emit Transfer(from, to, amount);
        return true;
    }
}

/// @dev Fee-on-transfer token: takes 1% on every transfer
contract FeeOnTransferToken is MockERC20 {
    uint256 public constant FEE_PCT = 1; // 1%

    constructor() MockERC20("FeeToken", "FEET") {}

    function transfer(address to, uint256 amount) external override returns (bool) {
        uint256 fee    = amount * FEE_PCT / 100;
        uint256 actual = amount - fee;
        balanceOf[msg.sender] -= amount;
        balanceOf[to]         += actual;
        // fee is burned (stays nowhere)
        emit Transfer(msg.sender, to, actual);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external override returns (bool) {
        if (allowance[from][msg.sender] != type(uint256).max) {
            allowance[from][msg.sender] -= amount;
        }
        uint256 fee    = amount * FEE_PCT / 100;
        uint256 actual = amount - fee;
        balanceOf[from] -= amount;
        balanceOf[to]   += actual;
        emit Transfer(from, to, actual);
        return true;
    }
}

/// @dev Token that does NOT return bool on transfer (old USDT style)
contract NonBoolToken {
    string  public name     = "NonBool";
    string  public symbol   = "NBT";
    uint8   public decimals = 6;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply   += amount;
    }

    function approve(address spender, uint256 amount) external {
        allowance[msg.sender][spender] = amount;
    }

    function transfer(address to, uint256 amount) external {
        balanceOf[msg.sender] -= amount;
        balanceOf[to]         += amount;
    }

    function transferFrom(address from, address to, uint256 amount) external {
        if (allowance[from][msg.sender] != type(uint256).max) {
            allowance[from][msg.sender] -= amount;
        }
        balanceOf[from] -= amount;
        balanceOf[to]   += amount;
    }
}

/// @dev Minimal WETH mock
contract MockWETH {
    string  public name     = "Wrapped Ether";
    string  public symbol   = "WETH";
    uint8   public decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
        totalSupply           += msg.value;
    }

    function withdraw(uint256 amount) external {
        balanceOf[msg.sender] -= amount;
        totalSupply           -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok, "ETH transfer failed");
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

    receive() external payable {
        balanceOf[msg.sender] += msg.value;
        totalSupply           += msg.value;
    }
}

/// @dev Minimal Permit2 stub (not used in direct transfer tests)
contract MockPermit2 {
    function permitTransferFrom(
        ISignatureTransfer.PermitTransferFrom memory,
        ISignatureTransfer.SignatureTransferDetails memory,
        address,
        bytes memory
    ) external pure {}
}

/// @dev Fake SwapRouter — returns 1:1 swap for simplicity
contract MockSwapRouter {
    IERC20 public tokenOut;

    function setTokenOut(address _t) external { tokenOut = IERC20(_t); }

    function exactInputSingle(ISwapRouter.ExactInputSingleParams calldata params)
        external payable returns (uint256)
    {
        // Pull tokenIn from caller
        IERC20(params.tokenIn).transferFrom(msg.sender, address(this), params.amountIn);
        // Send tokenOut to recipient (1:1)
        tokenOut.transfer(params.recipient, params.amountIn);
        return params.amountIn;
    }
}

/// @dev Reentrancy attacker — tries to call transferETHWithOracle in receive()
contract ReentrancyAttacker {
    FeeRouterV4 public target;
    bool public attacked;

    constructor(address _target) { target = FeeRouterV4(payable(_target)); }

    function attack(
        bytes32 nonce,
        uint256 deadline,
        bytes calldata sig
    ) external payable {
        target.transferETHWithOracle{value: msg.value}(
            address(this), nonce, deadline, sig
        );
    }

    receive() external payable {
        if (!attacked) {
            attacked = true;
            // Try to reenter — will fail due to nonReentrant
            // Use a different nonce to bypass NonceAlreadyUsed
            bytes32 nonce2 = keccak256("reenter");
            try target.transferETHWithOracle{value: msg.value}(
                address(this), nonce2, block.timestamp + 1 hours, hex""
            ) {} catch {}
        }
    }
}

// ═══════════════════════════════════════════════════════════════════
//  Main test contract
// ═══════════════════════════════════════════════════════════════════
contract FeeRouterV4Test is Test {
    FeeRouterV4    public router;
    MockERC20      public usdc;
    MockERC20      public dai;
    MockWETH       public weth;
    MockPermit2    public permit2;
    MockSwapRouter public swapRouter;

    // Oracle signer keypair (Foundry cheatcode)
    uint256 constant ORACLE_PK  = 0xA11CE;
    address          oracleSigner;

    // Wrong oracle keypair
    uint256 constant WRONG_PK   = 0xBAD;
    address          wrongSigner;

    address owner     = makeAddr("owner");
    address treasury  = makeAddr("treasury");
    address sender    = makeAddr("sender");
    address recipient = makeAddr("recipient");

    uint16  constant FEE_BPS = 50; // 0.5%
    uint16  constant BPS_DENOM = 10_000;

    // EIP-712 domain — must match the contract's constructor
    bytes32 constant ORACLE_TYPEHASH = keccak256(
        "OracleApproval(address sender,address recipient,"
        "address tokenIn,address tokenOut,uint256 amountIn,"
        "bytes32 nonce,uint256 deadline)"
    );

    function setUp() public {
        oracleSigner = vm.addr(ORACLE_PK);
        wrongSigner  = vm.addr(WRONG_PK);

        permit2    = new MockPermit2();
        weth       = new MockWETH();
        swapRouter = new MockSwapRouter();
        usdc       = new MockERC20("USD Coin", "USDC");
        dai        = new MockERC20("Dai", "DAI");

        router = new FeeRouterV4(
            address(permit2),
            treasury,
            oracleSigner,
            address(swapRouter),
            address(weth),
            FEE_BPS,
            owner
        );

        // Allowlist tokens
        vm.startPrank(owner);
        router.setTokenAllowed(address(usdc), true);
        router.setTokenAllowed(address(dai),  true);
        router.setTokenAllowed(address(weth), true);
        vm.stopPrank();

        // Fund sender
        vm.deal(sender, 1000 ether);
        usdc.mint(sender, 1_000_000e18);
        dai.mint(sender, 1_000_000e18);

        // Sender approves router
        vm.startPrank(sender);
        usdc.approve(address(router), type(uint256).max);
        dai.approve(address(router),  type(uint256).max);
        vm.stopPrank();

        // Fund swap router with tokenOut for swap tests
        usdc.mint(address(swapRouter), 10_000_000e18);
        dai.mint(address(swapRouter),  10_000_000e18);
        swapRouter.setTokenOut(address(usdc));
    }

    // ── EIP-712 signature helper ──────────────────────────────────────────
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

    function _freshNonce() internal view returns (bytes32) {
        return keccak256(abi.encodePacked(block.timestamp, gasleft()));
    }

    // ═══════════════════════════════════════════════════════════════════
    //  A) Fee calculation — fuzz
    // ═══════════════════════════════════════════════════════════════════

    function testFuzz_feeCalculationETH(uint256 amount) public {
        amount = bound(amount, 1e14, 100 ether);

        bytes32 nonce    = keccak256(abi.encodePacked("feeETH", amount));
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        uint256 treasuryBefore  = treasury.balance;
        uint256 recipientBefore = recipient.balance;

        vm.prank(sender);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        assertEq(treasury.balance  - treasuryBefore,  expectedFee, "treasury fee mismatch");
        assertEq(recipient.balance - recipientBefore, expectedNet, "recipient net mismatch");
        // No wei lost
        assertEq(expectedFee + expectedNet, amount, "wei leak detected");
    }

    function testFuzz_feeCalculationERC20(uint256 amount) public {
        amount = bound(amount, 1e6, 1_000_000e18);

        bytes32 nonce    = keccak256(abi.encodePacked("feeERC20", amount));
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(usdc), address(usdc), amount, nonce, deadline);

        uint256 treasuryBefore  = usdc.balanceOf(treasury);
        uint256 recipientBefore = usdc.balanceOf(recipient);

        vm.prank(sender);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sig);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        assertEq(usdc.balanceOf(treasury)  - treasuryBefore,  expectedFee, "treasury fee mismatch");
        assertEq(usdc.balanceOf(recipient) - recipientBefore, expectedNet, "recipient net mismatch");
        assertEq(expectedFee + expectedNet, amount, "wei leak detected");
    }

    function testFuzz_calcSplitView(uint256 amount) public view {
        amount = bound(amount, 0, type(uint128).max);
        (uint256 net, uint256 fee) = router.calcSplit(amount);
        assertEq(net + fee, amount, "split invariant broken");
        assertEq(fee, (amount * FEE_BPS) / BPS_DENOM, "fee formula mismatch");
    }

    // ═══════════════════════════════════════════════════════════════════
    //  B) Nonce replay
    // ═══════════════════════════════════════════════════════════════════

    function test_nonceReplay() public {
        bytes32 nonce    = keccak256("replay-nonce");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        // First call succeeds
        vm.prank(sender);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);

        assertTrue(router.isNonceUsed(nonce), "nonce should be marked used");

        // Second call with same nonce reverts
        vm.prank(sender);
        vm.expectRevert(NonceAlreadyUsed.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);
    }

    function test_nonceReplayERC20() public {
        bytes32 nonce    = keccak256("replay-erc20");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 100e18;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(usdc), address(usdc), amount, nonce, deadline);

        vm.prank(sender);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sig);

        vm.prank(sender);
        vm.expectRevert(NonceAlreadyUsed.selector);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sig);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  C) Oracle signature validation
    // ═══════════════════════════════════════════════════════════════════

    function test_invalidOracleSignature() public {
        bytes32 nonce    = keccak256("bad-sig");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;

        // Sign with wrong key
        bytes memory sig = _signOracle(WRONG_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(OracleSignatureInvalid.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);
    }

    function test_tamperedAmount() public {
        bytes32 nonce    = keccak256("tampered");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;

        // Sign for 1 ETH but send 2 ETH
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(OracleSignatureInvalid.selector);
        router.transferETHWithOracle{value: 2 ether}(recipient, nonce, deadline, sig);
    }

    function test_tamperedRecipient() public {
        bytes32 nonce    = keccak256("tampered-recipient");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;
        address fakeRecipient = makeAddr("fake");

        // Sign for `recipient` but call with `fakeRecipient`
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(OracleSignatureInvalid.selector);
        router.transferETHWithOracle{value: amount}(fakeRecipient, nonce, deadline, sig);
    }

    function test_expiredDeadline() public {
        bytes32 nonce    = keccak256("expired");
        uint256 deadline = block.timestamp - 1; // already expired
        uint256 amount   = 1 ether;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(DeadlineExpired.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);
    }

    function testFuzz_expiredDeadline(uint256 elapsed) public {
        elapsed = bound(elapsed, 1, 365 days);
        // Warp forward so subtraction doesn't underflow
        vm.warp(365 days + 1);
        uint256 deadline = block.timestamp - elapsed;

        bytes32 nonce    = keccak256(abi.encodePacked("fuzz-expired", elapsed));
        uint256 amount   = 1 ether;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(DeadlineExpired.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  D) Reentrancy protection
    // ═══════════════════════════════════════════════════════════════════

    function test_reentrancyETH() public {
        ReentrancyAttacker attacker = new ReentrancyAttacker(address(router));
        vm.deal(address(attacker), 10 ether);

        bytes32 nonce    = keccak256("reentrant");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;

        // Sign for the attacker as sender, attacker as recipient
        bytes memory sig = _signOracle(
            ORACLE_PK, address(attacker), address(attacker),
            address(0), address(0), amount, nonce, deadline
        );

        // The attacker's receive() tries to reenter — should fail silently
        // (the ReentrancyAttacker catches the revert)
        attacker.attack{value: amount}(nonce, deadline, sig);

        // The first call should have succeeded, the reentry should not
        assertTrue(router.isNonceUsed(nonce), "original nonce used");
        assertFalse(router.isNonceUsed(keccak256("reenter")), "reentrant nonce should NOT be used");
    }

    // ═══════════════════════════════════════════════════════════════════
    //  E) ERC20 edge cases
    // ═══════════════════════════════════════════════════════════════════

    function test_feeOnTransferToken() public {
        FeeOnTransferToken fot = new FeeOnTransferToken();

        vm.prank(owner);
        router.setTokenAllowed(address(fot), true);

        fot.mint(sender, 1_000e18);
        vm.prank(sender);
        fot.approve(address(router), type(uint256).max);

        bytes32 nonce    = keccak256("fot-test");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 100e18;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(fot), address(fot), amount, nonce, deadline);

        uint256 recipientBefore = fot.balanceOf(recipient);
        uint256 treasuryBefore  = fot.balanceOf(treasury);

        // transferWithOracle uses safeTransferFrom from sender directly
        // With a fee-on-transfer token, the recipient/treasury receive less than expected
        // The contract does NOT revert — it just transfers what it can (SafeERC20 succeeds)
        vm.prank(sender);
        router.transferWithOracle(address(fot), amount, recipient, nonce, deadline, sig);

        // Recipient and treasury got tokens (less than expected due to fee-on-transfer)
        uint256 recipientGot = fot.balanceOf(recipient) - recipientBefore;
        uint256 treasuryGot  = fot.balanceOf(treasury)  - treasuryBefore;
        assertTrue(recipientGot > 0, "recipient should receive tokens");
        assertTrue(treasuryGot  > 0, "treasury should receive tokens");
        // Total received < amount due to token's internal fee
        assertTrue(recipientGot + treasuryGot < amount, "fee-on-transfer should reduce total");
    }

    function test_nonBoolReturningToken() public {
        NonBoolToken nbt = new NonBoolToken();

        vm.prank(owner);
        router.setTokenAllowed(address(nbt), true);

        nbt.mint(sender, 1_000e6);
        vm.prank(sender);
        nbt.approve(address(router), type(uint256).max);

        bytes32 nonce    = keccak256("nbt-test");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 100e6;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(nbt), address(nbt), amount, nonce, deadline);

        // SafeERC20 handles non-bool-returning tokens
        vm.prank(sender);
        router.transferWithOracle(address(nbt), amount, recipient, nonce, deadline, sig);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;
        assertEq(nbt.balanceOf(recipient), expectedNet, "recipient balance wrong");
        assertEq(nbt.balanceOf(treasury),  expectedFee, "treasury balance wrong");
    }

    // ═══════════════════════════════════════════════════════════════════
    //  F) Zero amount / zero address
    // ═══════════════════════════════════════════════════════════════════

    function test_zeroAmountETH() public {
        bytes32 nonce    = keccak256("zero-eth");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), 0, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(ZeroAmount.selector);
        router.transferETHWithOracle{value: 0}(recipient, nonce, deadline, sig);
    }

    function test_zeroAmountERC20() public {
        bytes32 nonce    = keccak256("zero-erc20");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(usdc), address(usdc), 0, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(ZeroAmount.selector);
        router.transferWithOracle(address(usdc), 0, recipient, nonce, deadline, sig);
    }

    function test_zeroRecipientETH() public {
        bytes32 nonce    = keccak256("zero-recip-eth");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, address(0), address(0), address(0), 1 ether, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(ZeroAddress.selector);
        router.transferETHWithOracle{value: 1 ether}(address(0), nonce, deadline, sig);
    }

    function test_zeroRecipientERC20() public {
        bytes32 nonce    = keccak256("zero-recip-erc20");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, address(0), address(usdc), address(usdc), 100e18, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(ZeroAddress.selector);
        router.transferWithOracle(address(usdc), 100e18, address(0), nonce, deadline, sig);
    }

    function test_zeroTokenAddress() public {
        bytes32 nonce    = keccak256("zero-token");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), 100e18, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(ZeroAddress.selector);
        router.transferWithOracle(address(0), 100e18, recipient, nonce, deadline, sig);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  G) Blacklist & allowlist
    // ═══════════════════════════════════════════════════════════════════

    function test_blacklistedRecipientETH() public {
        vm.prank(owner);
        router.setBlacklisted(recipient, true);

        bytes32 nonce    = keccak256("blacklisted-eth");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(RecipientBlacklisted.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);
    }

    function test_blacklistedRecipientERC20() public {
        vm.prank(owner);
        router.setBlacklisted(recipient, true);

        bytes32 nonce    = keccak256("blacklisted-erc20");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 100e18;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(usdc), address(usdc), amount, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(RecipientBlacklisted.selector);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sig);
    }

    function test_tokenNotAllowed() public {
        MockERC20 rando = new MockERC20("Random", "RND");
        // NOT allowlisted

        bytes32 nonce    = keccak256("not-allowed");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 100e18;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(rando), address(rando), amount, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(TokenNotAllowed.selector);
        router.transferWithOracle(address(rando), amount, recipient, nonce, deadline, sig);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  H) Constructor validation
    // ═══════════════════════════════════════════════════════════════════

    function test_constructorZeroAddresses() public {
        vm.expectRevert(ZeroAddress.selector);
        new FeeRouterV4(address(0), treasury, oracleSigner, address(swapRouter), address(weth), FEE_BPS, owner);

        vm.expectRevert(ZeroAddress.selector);
        new FeeRouterV4(address(permit2), address(0), oracleSigner, address(swapRouter), address(weth), FEE_BPS, owner);

        vm.expectRevert(ZeroAddress.selector);
        new FeeRouterV4(address(permit2), treasury, address(0), address(swapRouter), address(weth), FEE_BPS, owner);

        vm.expectRevert(ZeroAddress.selector);
        new FeeRouterV4(address(permit2), treasury, oracleSigner, address(0), address(weth), FEE_BPS, owner);

        vm.expectRevert(ZeroAddress.selector);
        new FeeRouterV4(address(permit2), treasury, oracleSigner, address(swapRouter), address(0), FEE_BPS, owner);
    }

    function test_constructorFeeTooHigh() public {
        vm.expectRevert(FeeTooHigh.selector);
        new FeeRouterV4(address(permit2), treasury, oracleSigner, address(swapRouter), address(weth), 1001, owner);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  I) Owner functions
    // ═══════════════════════════════════════════════════════════════════

    function test_setFeeBps() public {
        vm.prank(owner);
        router.setFeeBps(100); // 1%
        assertEq(router.feeBps(), 100);

        vm.prank(owner);
        vm.expectRevert(FeeTooHigh.selector);
        router.setFeeBps(1001);
    }

    function test_setOracleSigner() public {
        address newSigner = makeAddr("newOracle");
        vm.prank(owner);
        router.setOracleSigner(newSigner);
        assertEq(router.oracleSigner(), newSigner);

        vm.prank(owner);
        vm.expectRevert(ZeroAddress.selector);
        router.setOracleSigner(address(0));
    }

    function test_onlyOwner() public {
        vm.prank(sender); // not owner
        vm.expectRevert();
        router.setFeeBps(100);

        vm.prank(sender);
        vm.expectRevert();
        router.setOracleSigner(makeAddr("x"));

        vm.prank(sender);
        vm.expectRevert();
        router.setTokenAllowed(address(usdc), false);

        vm.prank(sender);
        vm.expectRevert();
        router.setBlacklisted(sender, true);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  J) Swap functions
    // ═══════════════════════════════════════════════════════════════════

    function test_swapAndSend() public {
        // Approve router to pull DAI from sender
        // (already done in setUp for dai)
        // Fund swap router with USDC output
        swapRouter.setTokenOut(address(usdc));

        bytes32 nonce    = keccak256("swap-test");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amountIn = 100e18;
        uint256 minOut   = 1; // mock returns 1:1

        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(dai), address(usdc), amountIn, nonce, deadline);

        uint256 recipientBefore = usdc.balanceOf(recipient);
        uint256 treasuryBefore  = usdc.balanceOf(treasury);

        vm.prank(sender);
        router.swapAndSend(address(dai), address(usdc), amountIn, minOut, recipient, nonce, deadline, sig);

        // Mock swaps 1:1, so amountOut = amountIn
        uint256 expectedFee = (amountIn * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amountIn - expectedFee;

        assertEq(usdc.balanceOf(recipient) - recipientBefore, expectedNet, "swap recipient mismatch");
        assertEq(usdc.balanceOf(treasury)  - treasuryBefore,  expectedFee, "swap treasury mismatch");
    }

    function test_swapAndSend_MEVGuard() public {
        bytes32 nonce    = keccak256("mev-guard");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(dai), address(usdc), 100e18, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(MEVGuard.selector);
        router.swapAndSend(address(dai), address(usdc), 100e18, 0, recipient, nonce, deadline, sig);
    }

    function test_swapAndSend_sameToken() public {
        bytes32 nonce    = keccak256("same-token");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(usdc), address(usdc), 100e18, nonce, deadline);

        vm.prank(sender);
        vm.expectRevert(SameToken.selector);
        router.swapAndSend(address(usdc), address(usdc), 100e18, 1, recipient, nonce, deadline, sig);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  K) Happy path — full flow ETH
    // ═══════════════════════════════════════════════════════════════════

    function test_happyPath_ETH() public {
        uint256 amount   = 5 ether;
        bytes32 nonce    = keccak256("happy-eth");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        uint256 senderBefore    = sender.balance;
        uint256 recipientBefore = recipient.balance;
        uint256 treasuryBefore  = treasury.balance;

        vm.prank(sender);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        assertEq(recipient.balance - recipientBefore, expectedNet);
        assertEq(treasury.balance  - treasuryBefore,  expectedFee);
        assertEq(senderBefore - sender.balance, amount);
    }

    function test_happyPath_ERC20() public {
        uint256 amount   = 500e18;
        bytes32 nonce    = keccak256("happy-erc20");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(usdc), address(usdc), amount, nonce, deadline);

        vm.prank(sender);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sig);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        assertEq(usdc.balanceOf(recipient), expectedNet);
        assertEq(usdc.balanceOf(treasury),  expectedFee);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  L) Events
    // ═══════════════════════════════════════════════════════════════════

    function test_emitsPaymentProcessed() public {
        uint256 amount   = 2 ether;
        bytes32 nonce    = keccak256("event-test");
        uint256 deadline = block.timestamp + 1 hours;
        bytes memory sig = _signOracle(ORACLE_PK, sender, recipient, address(0), address(0), amount, nonce, deadline);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        vm.expectEmit(true, true, true, true);
        emit FeeRouterV4.PaymentProcessed(sender, recipient, address(0), amount, expectedNet, expectedFee, nonce, false);

        vm.prank(sender);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sig);
    }
}
