// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/FeeRouterV4_1.sol";

contract MockERC20Simple is IERC20 {
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

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to]         += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (allowance[from][msg.sender] != type(uint256).max) {
            allowance[from][msg.sender] -= amount;
        }
        balanceOf[from] -= amount;
        balanceOf[to]   += amount;
        emit Transfer(from, to, amount);
        return true;
    }
}

contract MockWETH41 {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function deposit() external payable { balanceOf[msg.sender] += msg.value; }
    function withdraw(uint256 amount) external {
        balanceOf[msg.sender] -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
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
        if (allowance[from][msg.sender] != type(uint256).max) allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to]   += amount;
        return true;
    }
    receive() external payable { balanceOf[msg.sender] += msg.value; }
}

contract MockPermit241 {
    function permitTransferFrom(
        ISignatureTransfer.PermitTransferFrom memory,
        ISignatureTransfer.SignatureTransferDetails memory,
        address, bytes memory
    ) external pure {}
}

contract MockSwapRouter41 {
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

contract FeeRouterV4_1Test is Test {
    FeeRouterV4_1   public router;
    MockERC20Simple public usdc;
    MockWETH41      public weth;
    MockPermit241   public permit2;
    MockSwapRouter41 public swapRouter;

    address owner    = makeAddr("owner");
    address treasury = makeAddr("treasury");
    address attacker = makeAddr("attacker");

    function setUp() public {
        permit2    = new MockPermit241();
        weth       = new MockWETH41();
        swapRouter = new MockSwapRouter41();
        usdc       = new MockERC20Simple("USD Coin", "USDC");

        router = new FeeRouterV4_1(
            address(permit2),
            treasury,
            makeAddr("oracle"),
            address(swapRouter),
            address(weth),
            50,     // 0.5% fee
            owner
        );

        vm.prank(owner);
        router.setTokenAllowed(address(usdc), true);
    }

    // ── emergencyWithdrawETH ──────────────────────────────────────────────

    function test_emergencyWithdrawETH_OwnerCanRecover() public {
        vm.deal(address(router), 5 ether);
        assertEq(address(router).balance, 5 ether);

        vm.prank(owner);
        router.emergencyWithdrawETH(payable(treasury));

        assertEq(address(router).balance, 0);
        assertEq(treasury.balance, 5 ether);
    }

    function test_emergencyWithdrawETH_EmitsEvent() public {
        vm.deal(address(router), 1 ether);

        vm.expectEmit(true, false, false, true);
        emit FeeRouterV4_1.EmergencyETHWithdrawn(treasury, 1 ether);

        vm.prank(owner);
        router.emergencyWithdrawETH(payable(treasury));
    }

    function test_emergencyWithdrawETH_RevertsForNonOwner() public {
        vm.deal(address(router), 1 ether);

        vm.prank(attacker);
        vm.expectRevert();
        router.emergencyWithdrawETH(payable(attacker));

        assertEq(address(router).balance, 1 ether);
    }

    function test_emergencyWithdrawETH_RevertsOnZeroBalance() public {
        vm.prank(owner);
        vm.expectRevert("No ETH to withdraw");
        router.emergencyWithdrawETH(payable(treasury));
    }

    function test_emergencyWithdrawETH_RevertsOnZeroRecipient() public {
        vm.deal(address(router), 1 ether);

        vm.prank(owner);
        vm.expectRevert("Zero recipient");
        router.emergencyWithdrawETH(payable(address(0)));
    }

    // ── emergencyWithdrawToken ────────────────────────────────────────────

    function test_emergencyWithdrawToken_OwnerCanRecover() public {
        usdc.mint(address(router), 1000e18);
        assertEq(usdc.balanceOf(address(router)), 1000e18);

        vm.prank(owner);
        router.emergencyWithdrawToken(address(usdc), treasury);

        assertEq(usdc.balanceOf(address(router)), 0);
        assertEq(usdc.balanceOf(treasury), 1000e18);
    }

    function test_emergencyWithdrawToken_EmitsEvent() public {
        usdc.mint(address(router), 500e18);

        vm.expectEmit(true, true, false, true);
        emit FeeRouterV4_1.EmergencyTokenWithdrawn(address(usdc), treasury, 500e18);

        vm.prank(owner);
        router.emergencyWithdrawToken(address(usdc), treasury);
    }

    function test_emergencyWithdrawToken_RevertsForNonOwner() public {
        usdc.mint(address(router), 1000e18);

        vm.prank(attacker);
        vm.expectRevert();
        router.emergencyWithdrawToken(address(usdc), attacker);

        assertEq(usdc.balanceOf(address(router)), 1000e18);
    }

    function test_emergencyWithdrawToken_RevertsOnZeroBalance() public {
        vm.prank(owner);
        vm.expectRevert("No token to withdraw");
        router.emergencyWithdrawToken(address(usdc), treasury);
    }

    function test_emergencyWithdrawToken_RevertsOnZeroRecipient() public {
        usdc.mint(address(router), 100e18);

        vm.prank(owner);
        vm.expectRevert("Zero recipient");
        router.emergencyWithdrawToken(address(usdc), address(0));
    }

    // ── receive() still works ─────────────────────────────────────────────

    function test_receiveAcceptsETH() public {
        vm.deal(address(this), 1 ether);
        (bool ok,) = address(router).call{value: 1 ether}("");
        assertTrue(ok);
        assertEq(address(router).balance, 1 ether);
    }

    // ── EIP-712 fork replay protection ──────────────────────────────────

    function test_domainSeparatorChangesOnFork() public {
        bytes32 ds1 = router.domainSeparator();

        // Simulate chain fork by changing chainid
        vm.chainId(999999);

        bytes32 ds2 = router.domainSeparator();
        assertTrue(ds1 != ds2, "Domain separator must change after fork");
    }

    function test_domainSeparatorStableOnSameChain() public {
        bytes32 ds1 = router.domainSeparator();
        bytes32 ds2 = router.domainSeparator();
        assertEq(ds1, ds2);
    }

    function test_forkRejectsOriginalChainSignature() public {
        // Setup: create a valid oracle signature on the original chain
        (address oracleSigner, uint256 oraclePk) = makeAddrAndKey("forkOracle");
        vm.prank(owner);
        router.setOracleSigner(oracleSigner);

        address sender    = makeAddr("sender");
        address recipient = makeAddr("recipient");
        address token     = address(usdc);
        uint256 amount    = 1000e18;
        bytes32 nonce     = keccak256("fork-test-nonce");
        uint256 deadline  = block.timestamp + 300;

        // Build EIP-712 digest on current chain
        bytes32 structHash = keccak256(abi.encode(
            keccak256("OracleApproval(address sender,address recipient,address tokenIn,address tokenOut,uint256 amountIn,bytes32 nonce,uint256 deadline)"),
            sender, recipient, token, token, amount, nonce, deadline
        ));
        bytes32 domainSep = router.domainSeparator();
        bytes32 digest    = keccak256(abi.encodePacked("\x19\x01", domainSep, structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(oraclePk, digest);
        bytes memory sig = abi.encodePacked(r, s, v);

        // Fork: change chain id
        vm.chainId(999999);

        // Fund sender and approve
        usdc.mint(sender, amount);
        vm.prank(sender);
        usdc.approve(address(router), amount);

        // Attempt transfer with original-chain signature — must revert
        vm.prank(sender);
        vm.expectRevert(OracleSignatureInvalid.selector);
        router.transferWithOracle(token, amount, recipient, nonce, deadline, sig);
    }

    // ── eip712Domain() introspection ────────────────────────────────────

    function test_eip712DomainReturnsCorrectValues() public view {
        (
            bytes1 fields,
            string memory name,
            string memory version,
            uint256 chainId,
            address verifyingContract,
            ,
        ) = router.eip712Domain();

        assertEq(uint8(fields), 0x0f); // name | version | chainId | verifyingContract
        assertEq(keccak256(bytes(name)), keccak256(bytes("FeeRouterV4_1")));
        assertEq(keccak256(bytes(version)), keccak256(bytes("4.1")));
        assertEq(chainId, block.chainid);
        assertEq(verifyingContract, address(router));
    }
}
