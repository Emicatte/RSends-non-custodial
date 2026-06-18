// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/FeeRouterV5.sol";

// ═══════════════════════════════════════════════════════════════════
//  Mock contracts (same patterns as V4 tests)
// ═══════════════════════════════════════════════════════════════════

contract MockERC20V5 is IERC20 {
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

contract MockWETHV5 {
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

contract MockPermit2V5 {
    function permitTransferFrom(
        ISignatureTransfer.PermitTransferFrom memory,
        ISignatureTransfer.SignatureTransferDetails memory,
        address,
        bytes memory
    ) external pure {}
}

contract MockSwapRouterV5 {
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
contract FeeRouterV5Test is Test {
    FeeRouterV5     public router;
    MockERC20V5     public usdc;
    MockERC20V5     public dai;
    MockWETHV5      public weth;
    MockPermit2V5   public permit2;
    MockSwapRouterV5 public swapRouter;

    // 3 oracle signers for 2-of-3 multi-sig
    uint256 constant ORACLE_PK1 = 0xA11CE;
    uint256 constant ORACLE_PK2 = 0xB0B;
    uint256 constant ORACLE_PK3 = 0xCAFE;
    address oracle1;
    address oracle2;
    address oracle3;

    uint256 constant WRONG_PK = 0xBAD;
    address wrongSigner;

    address owner     = makeAddr("owner");
    address treasury  = makeAddr("treasury");
    address sender_   = makeAddr("sender");
    address recipient = makeAddr("recipient");

    uint16  constant FEE_BPS   = 50; // 0.5%
    uint16  constant BPS_DENOM = 10_000;

    bytes32 constant ORACLE_TYPEHASH = keccak256(
        "OracleApproval(address sender,address recipient,"
        "address tokenIn,address tokenOut,uint256 amountIn,"
        "bytes32 nonce,uint256 deadline)"
    );

    function setUp() public {
        oracle1     = vm.addr(ORACLE_PK1);
        oracle2     = vm.addr(ORACLE_PK2);
        oracle3     = vm.addr(ORACLE_PK3);
        wrongSigner = vm.addr(WRONG_PK);

        permit2    = new MockPermit2V5();
        weth       = new MockWETHV5();
        swapRouter = new MockSwapRouterV5();
        usdc       = new MockERC20V5("USD Coin", "USDC");
        dai        = new MockERC20V5("Dai", "DAI");

        // Sort signers ascending for constructor
        address[] memory signers = _sortedSigners();

        router = new FeeRouterV5(
            address(permit2),
            treasury,
            signers,
            2,  // threshold = 2-of-3
            address(swapRouter),
            address(weth),
            FEE_BPS,
            owner
        );

        vm.startPrank(owner);
        router.setTokenAllowed(address(usdc), true);
        router.setTokenAllowed(address(dai),  true);
        router.setTokenAllowed(address(weth), true);
        vm.stopPrank();

        vm.deal(sender_, 1000 ether);
        usdc.mint(sender_, 1_000_000e18);
        dai.mint(sender_, 1_000_000e18);

        vm.startPrank(sender_);
        usdc.approve(address(router), type(uint256).max);
        dai.approve(address(router),  type(uint256).max);
        vm.stopPrank();

        usdc.mint(address(swapRouter), 10_000_000e18);
        dai.mint(address(swapRouter),  10_000_000e18);
        swapRouter.setTokenOut(address(usdc));
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    function _sortedSigners() internal view returns (address[] memory) {
        address[] memory s = new address[](3);
        s[0] = oracle1;
        s[1] = oracle2;
        s[2] = oracle3;
        // Bubble sort (3 elements)
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
        // Sign with each pk, then sort by recovered address ascending
        bytes[] memory sigs = new bytes[](pks.length);
        address[] memory addrs = new address[](pks.length);

        for (uint256 i = 0; i < pks.length; i++) {
            sigs[i] = _signOracle(pks[i], _sender, _recipient, _tokenIn, _tokenOut, _amountIn, _nonce, _deadline);
            addrs[i] = vm.addr(pks[i]);
        }

        // Bubble sort by address
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

    function _sign3of3(
        address _sender,
        address _recipient,
        address _tokenIn,
        address _tokenOut,
        uint256 _amountIn,
        bytes32 _nonce,
        uint256 _deadline
    ) internal view returns (bytes[] memory) {
        uint256[] memory pks = new uint256[](3);
        pks[0] = ORACLE_PK1;
        pks[1] = ORACLE_PK2;
        pks[2] = ORACLE_PK3;
        return _signMulti(pks, _sender, _recipient, _tokenIn, _tokenOut, _amountIn, _nonce, _deadline);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  A) Multi-sig oracle — happy path (2-of-3)
    // ═══════════════════════════════════════════════════════════════════

    function test_happyPath_2of3_ETH() public {
        uint256 amount   = 5 ether;
        bytes32 nonce    = keccak256("multi-eth");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = _sign2of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        uint256 recipientBefore = recipient.balance;
        uint256 treasuryBefore  = treasury.balance;

        vm.prank(sender_);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        assertEq(recipient.balance - recipientBefore, expectedNet, "recipient net mismatch");
        assertEq(treasury.balance  - treasuryBefore,  expectedFee, "treasury fee mismatch");
    }

    function test_happyPath_2of3_ERC20() public {
        uint256 amount   = 500e18;
        bytes32 nonce    = keccak256("multi-erc20");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = _sign2of3(sender_, recipient, address(usdc), address(usdc), amount, nonce, deadline);

        vm.prank(sender_);
        router.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sigs);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        assertEq(usdc.balanceOf(recipient), expectedNet, "recipient balance");
        assertEq(usdc.balanceOf(treasury),  expectedFee, "treasury balance");
    }

    function test_happyPath_3of3_ETH() public {
        uint256 amount   = 2 ether;
        bytes32 nonce    = keccak256("3of3-eth");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = _sign3of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender_);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);

        assertTrue(router.isNonceUsed(nonce));
    }

    // ═══════════════════════════════════════════════════════════════════
    //  B) Insufficient signatures reverts
    // ═══════════════════════════════════════════════════════════════════

    function test_insufficientSignaturesReverts() public {
        uint256 amount   = 1 ether;
        bytes32 nonce    = keccak256("insufficient");
        uint256 deadline = block.timestamp + 1 hours;

        // Only 1 signature for threshold=2
        uint256[] memory pks = new uint256[](1);
        pks[0] = ORACLE_PK1;
        bytes[] memory sigs = _signMulti(pks, sender_, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender_);
        vm.expectRevert(InsufficientSignatures.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);
    }

    function test_emptySignaturesReverts() public {
        uint256 amount   = 1 ether;
        bytes32 nonce    = keccak256("empty-sigs");
        uint256 deadline = block.timestamp + 1 hours;

        bytes[] memory sigs = new bytes[](0);

        vm.prank(sender_);
        vm.expectRevert(InsufficientSignatures.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  C) Invalid / wrong signer reverts
    // ═══════════════════════════════════════════════════════════════════

    function test_wrongSignerReverts() public {
        uint256 amount   = 1 ether;
        bytes32 nonce    = keccak256("wrong-signer");
        uint256 deadline = block.timestamp + 1 hours;

        // One valid + one wrong signer
        uint256[] memory pks = new uint256[](2);
        pks[0] = ORACLE_PK1;
        pks[1] = WRONG_PK;
        bytes[] memory sigs = _signMulti(pks, sender_, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender_);
        vm.expectRevert(OracleSignatureInvalid.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  D) Duplicate signatures reverts (not ascending)
    // ═══════════════════════════════════════════════════════════════════

    function test_duplicateSignatureReverts() public {
        uint256 amount   = 1 ether;
        bytes32 nonce    = keccak256("dup-sig");
        uint256 deadline = block.timestamp + 1 hours;

        bytes memory sig1 = _signOracle(ORACLE_PK1, sender_, recipient, address(0), address(0), amount, nonce, deadline);

        // Same signer twice — not ascending
        bytes[] memory sigs = new bytes[](2);
        sigs[0] = sig1;
        sigs[1] = sig1;

        vm.prank(sender_);
        vm.expectRevert(SignersNotAscending.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  E) Nonce replay
    // ═══════════════════════════════════════════════════════════════════

    function test_nonceReplay() public {
        bytes32 nonce    = keccak256("replay-v5");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;
        bytes[] memory sigs = _sign2of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender_);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);

        assertTrue(router.isNonceUsed(nonce));

        vm.prank(sender_);
        vm.expectRevert(NonceAlreadyUsed.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  F) Tampered data reverts
    // ═══════════════════════════════════════════════════════════════════

    function test_tamperedAmount() public {
        bytes32 nonce    = keccak256("tampered-v5");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;

        bytes[] memory sigs = _sign2of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        // Send 2 ETH but signed for 1 ETH
        vm.prank(sender_);
        vm.expectRevert(OracleSignatureInvalid.selector);
        router.transferETHWithOracle{value: 2 ether}(recipient, nonce, deadline, sigs);
    }

    function test_tamperedRecipient() public {
        bytes32 nonce    = keccak256("tampered-recip-v5");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;
        address fakeRecipient = makeAddr("fake");

        bytes[] memory sigs = _sign2of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender_);
        vm.expectRevert(OracleSignatureInvalid.selector);
        router.transferETHWithOracle{value: amount}(fakeRecipient, nonce, deadline, sigs);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  G) Deadline expired
    // ═══════════════════════════════════════════════════════════════════

    function test_expiredDeadline() public {
        bytes32 nonce    = keccak256("expired-v5");
        uint256 deadline = block.timestamp - 1;
        uint256 amount   = 1 ether;
        bytes[] memory sigs = _sign2of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender_);
        vm.expectRevert(DeadlineExpired.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  H) Constructor validation
    // ═══════════════════════════════════════════════════════════════════

    function test_constructorEmptySigners() public {
        address[] memory empty = new address[](0);
        vm.expectRevert(EmptySigners.selector);
        new FeeRouterV5(address(permit2), treasury, empty, 1, address(swapRouter), address(weth), FEE_BPS, owner);
    }

    function test_constructorThresholdZero() public {
        address[] memory signers = _sortedSigners();
        vm.expectRevert(ThresholdTooHigh.selector);
        new FeeRouterV5(address(permit2), treasury, signers, 0, address(swapRouter), address(weth), FEE_BPS, owner);
    }

    function test_constructorThresholdTooHigh() public {
        address[] memory signers = _sortedSigners();
        vm.expectRevert(ThresholdTooHigh.selector);
        new FeeRouterV5(address(permit2), treasury, signers, 4, address(swapRouter), address(weth), FEE_BPS, owner);
    }

    function test_constructorDuplicateSigner() public {
        address[] memory signers = new address[](2);
        signers[0] = oracle1;
        signers[1] = oracle1; // duplicate
        vm.expectRevert(); // DuplicateSigner or address ordering error
        new FeeRouterV5(address(permit2), treasury, signers, 2, address(swapRouter), address(weth), FEE_BPS, owner);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  I) setOracleSigners — owner only
    // ═══════════════════════════════════════════════════════════════════

    function test_setOracleSigners() public {
        address newSigner1 = makeAddr("new1");
        address newSigner2 = makeAddr("new2");

        address[] memory newSigners = new address[](2);
        if (newSigner1 < newSigner2) {
            newSigners[0] = newSigner1;
            newSigners[1] = newSigner2;
        } else {
            newSigners[0] = newSigner2;
            newSigners[1] = newSigner1;
        }

        vm.prank(owner);
        router.setOracleSigners(newSigners, 2);

        assertEq(router.oracleThreshold(), 2);
        assertTrue(router.isOracleSigner(newSigners[0]));
        assertTrue(router.isOracleSigner(newSigners[1]));
        // Old signers removed
        assertFalse(router.isOracleSigner(oracle1));
        assertFalse(router.isOracleSigner(oracle2));
        assertFalse(router.isOracleSigner(oracle3));
    }

    function test_setOracleSignersNotOwner() public {
        address[] memory signers = _sortedSigners();
        vm.prank(sender_);
        vm.expectRevert();
        router.setOracleSigners(signers, 2);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  J) getOracleSigners view
    // ═══════════════════════════════════════════════════════════════════

    function test_getOracleSigners() public view {
        address[] memory signers = router.getOracleSigners();
        assertEq(signers.length, 3);
        assertEq(router.oracleThreshold(), 2);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  K) Swap with multi-sig
    // ═══════════════════════════════════════════════════════════════════

    function test_swapAndSend_multiSig() public {
        swapRouter.setTokenOut(address(usdc));

        bytes32 nonce    = keccak256("swap-v5");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amountIn = 100e18;
        uint256 minOut   = 1;

        bytes[] memory sigs = _sign2of3(sender_, recipient, address(dai), address(usdc), amountIn, nonce, deadline);

        uint256 recipientBefore = usdc.balanceOf(recipient);
        uint256 treasuryBefore  = usdc.balanceOf(treasury);

        vm.prank(sender_);
        router.swapAndSend(address(dai), address(usdc), amountIn, minOut, recipient, nonce, deadline, sigs);

        uint256 expectedFee = (amountIn * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amountIn - expectedFee;

        assertEq(usdc.balanceOf(recipient) - recipientBefore, expectedNet, "swap recipient");
        assertEq(usdc.balanceOf(treasury)  - treasuryBefore,  expectedFee, "swap treasury");
    }

    // ═══════════════════════════════════════════════════════════════════
    //  L) Fee calculation — fuzz
    // ═══════════════════════════════════════════════════════════════════

    function testFuzz_feeCalculation(uint256 amount) public {
        amount = bound(amount, 1e14, 100 ether);

        bytes32 nonce    = keccak256(abi.encodePacked("fuzz-v5", amount));
        uint256 deadline = block.timestamp + 1 hours;
        bytes[] memory sigs = _sign2of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        uint256 treasuryBefore  = treasury.balance;
        uint256 recipientBefore = recipient.balance;

        vm.prank(sender_);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        assertEq(treasury.balance  - treasuryBefore,  expectedFee, "treasury fee");
        assertEq(recipient.balance - recipientBefore, expectedNet, "recipient net");
        assertEq(expectedFee + expectedNet, amount, "no wei leak");
    }

    // ═══════════════════════════════════════════════════════════════════
    //  M) Events
    // ═══════════════════════════════════════════════════════════════════

    function test_emitsPaymentProcessed() public {
        uint256 amount   = 2 ether;
        bytes32 nonce    = keccak256("event-v5");
        uint256 deadline = block.timestamp + 1 hours;
        bytes[] memory sigs = _sign2of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;

        vm.expectEmit(true, true, true, true);
        emit FeeRouterV5.PaymentProcessed(sender_, recipient, address(0), amount, expectedNet, expectedFee, nonce, false);

        vm.prank(sender_);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  N) Blacklist & allowlist still work
    // ═══════════════════════════════════════════════════════════════════

    function test_blacklistedRecipient() public {
        vm.prank(owner);
        router.setBlacklisted(recipient, true);

        bytes32 nonce    = keccak256("blacklisted-v5");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 1 ether;
        bytes[] memory sigs = _sign2of3(sender_, recipient, address(0), address(0), amount, nonce, deadline);

        vm.prank(sender_);
        vm.expectRevert(RecipientBlacklisted.selector);
        router.transferETHWithOracle{value: amount}(recipient, nonce, deadline, sigs);
    }

    function test_tokenNotAllowed() public {
        MockERC20V5 rando = new MockERC20V5("Random", "RND");

        bytes32 nonce    = keccak256("not-allowed-v5");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 100e18;
        bytes[] memory sigs = _sign2of3(sender_, recipient, address(rando), address(rando), amount, nonce, deadline);

        vm.prank(sender_);
        vm.expectRevert(TokenNotAllowed.selector);
        router.transferWithOracle(address(rando), amount, recipient, nonce, deadline, sigs);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  O) Emergency rescue still works
    // ═══════════════════════════════════════════════════════════════════

    function test_emergencyWithdrawETH() public {
        vm.deal(address(router), 1 ether);

        vm.prank(owner);
        router.emergencyWithdrawETH(payable(owner));

        assertEq(address(router).balance, 0);
        assertEq(owner.balance, 1 ether);
    }

    function test_emergencyWithdrawToken() public {
        usdc.mint(address(router), 1000e18);

        vm.prank(owner);
        router.emergencyWithdrawToken(address(usdc), owner);

        assertEq(usdc.balanceOf(address(router)), 0);
        assertEq(usdc.balanceOf(owner), 1000e18);
    }

    // ═══════════════════════════════════════════════════════════════════
    //  P) Threshold-of-1 (single signer mode — backward compat)
    // ═══════════════════════════════════════════════════════════════════

    function test_thresholdOfOne() public {
        // Deploy a 1-of-1 config
        address[] memory signers = new address[](1);
        signers[0] = oracle1;

        FeeRouterV5 r1 = new FeeRouterV5(
            address(permit2), treasury, signers, 1,
            address(swapRouter), address(weth), FEE_BPS, owner
        );

        vm.prank(owner);
        r1.setTokenAllowed(address(usdc), true);

        usdc.mint(sender_, 1000e18);
        vm.prank(sender_);
        usdc.approve(address(r1), type(uint256).max);

        bytes32 nonce    = keccak256("1of1");
        uint256 deadline = block.timestamp + 1 hours;
        uint256 amount   = 100e18;

        bytes32 domainSep = r1.domainSeparator();
        bytes32 structHash = keccak256(abi.encode(
            ORACLE_TYPEHASH, sender_, recipient, address(usdc), address(usdc), amount, nonce, deadline
        ));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", domainSep, structHash));
        (uint8 v, bytes32 r_, bytes32 s) = vm.sign(ORACLE_PK1, digest);

        bytes[] memory sigs = new bytes[](1);
        sigs[0] = abi.encodePacked(r_, s, v);

        vm.prank(sender_);
        r1.transferWithOracle(address(usdc), amount, recipient, nonce, deadline, sigs);

        uint256 expectedFee = (amount * FEE_BPS) / BPS_DENOM;
        uint256 expectedNet = amount - expectedFee;
        assertEq(usdc.balanceOf(recipient), expectedNet);
    }
}
