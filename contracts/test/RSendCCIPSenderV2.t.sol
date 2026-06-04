// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/RSendCCIPSenderV2.sol";

contract MockERC20CCIP is IERC20 {
    string  public name;
    string  public symbol;
    uint8   public decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    constructor(string memory _n, string memory _s) { name = _n; symbol = _s; }

    function mint(address to, uint256 a) external { balanceOf[to] += a; totalSupply += a; }
    function approve(address s, uint256 a) external returns (bool) { allowance[msg.sender][s] = a; return true; }
    function transfer(address to, uint256 a) external returns (bool) {
        balanceOf[msg.sender] -= a; balanceOf[to] += a; return true;
    }
    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        if (allowance[f][msg.sender] != type(uint256).max) allowance[f][msg.sender] -= a;
        balanceOf[f] -= a; balanceOf[t] += a; return true;
    }
}

contract MockCCIPRouter {
    bytes public lastExtraArgs;
    uint256 public constant MOCK_FEE = 0.01 ether;

    function getFee(uint64, IRouterClient.EVM2AnyMessage memory message)
        external view returns (uint256)
    {
        // Fee increases slightly when extraArgs are non-empty (realistic behavior)
        return message.extraArgs.length > 0 ? MOCK_FEE : MOCK_FEE / 2;
    }

    function ccipSend(uint64, IRouterClient.EVM2AnyMessage calldata message)
        external payable returns (bytes32)
    {
        lastExtraArgs = message.extraArgs;
        // Pull tokens from sender (mimics real router)
        if (message.tokenAmounts.length > 0) {
            IERC20(message.tokenAmounts[0].token).transferFrom(
                msg.sender, address(this), message.tokenAmounts[0].amount
            );
        }
        return keccak256(abi.encode(block.timestamp, msg.sender));
    }

    function isChainSupported(uint64) external pure returns (bool) { return true; }
}

contract MockWETHCCIP {
    mapping(address => uint256) public balanceOf;
    function deposit() external payable { balanceOf[msg.sender] += msg.value; }
    function withdraw(uint256 a) external { balanceOf[msg.sender] -= a; payable(msg.sender).transfer(a); }
    function approve(address, uint256) external returns (bool) { return true; }
    receive() external payable {}
}

contract MockSwapRouterCCIP {
    IERC20 public tokenOut;
    function setTokenOut(address t) external { tokenOut = IERC20(t); }
    function exactInputSingle(ISwapRouter.ExactInputSingleParams calldata p)
        external payable returns (uint256)
    {
        IERC20(p.tokenIn).transferFrom(msg.sender, address(this), p.amountIn);
        tokenOut.transfer(p.recipient, p.amountIn);
        return p.amountIn;
    }
}

contract RSendCCIPSenderV2Test is Test {
    RSendCCIPSenderV2 public sender;
    MockCCIPRouter    public router;
    MockERC20CCIP     public usdc;
    MockWETHCCIP      public weth;
    MockSwapRouterCCIP public swapRouter;

    address owner     = makeAddr("owner");
    address treasury  = makeAddr("treasury");
    address user      = makeAddr("user");
    address recipient = makeAddr("recipient");
    address receiver  = makeAddr("destReceiver");
    uint64  constant DEST_CHAIN = 16015286601757825753; // Sepolia selector

    bytes4 constant EVM_EXTRA_ARGS_V1_TAG = 0x97a657c9;

    function setUp() public {
        router     = new MockCCIPRouter();
        usdc       = new MockERC20CCIP("USDC", "USDC");
        weth       = new MockWETHCCIP();
        swapRouter = new MockSwapRouterCCIP();

        sender = new RSendCCIPSenderV2(
            address(router),
            treasury,
            address(swapRouter),
            address(weth),
            owner
        );

        vm.startPrank(owner);
        sender.setTokenAllowed(address(usdc), true);
        sender.setReceiver(DEST_CHAIN, receiver);
        vm.stopPrank();

        usdc.mint(user, 1_000_000e18);
        vm.prank(user);
        usdc.approve(address(sender), type(uint256).max);

        vm.deal(user, 100 ether);
    }

    // ── extraArgs encoding ────────────────────────────────────────────────

    function test_extraArgsNonEmpty() public {
        vm.prank(user);
        sender.sendCrossChain{value: 1 ether}(DEST_CHAIN, recipient, address(usdc), 1000e18);

        bytes memory args = router.lastExtraArgs();
        assertTrue(args.length > 0, "extraArgs must be non-empty");
    }

    function test_extraArgsContainsCorrectTag() public {
        vm.prank(user);
        sender.sendCrossChain{value: 1 ether}(DEST_CHAIN, recipient, address(usdc), 1000e18);

        bytes memory args = router.lastExtraArgs();
        bytes4 tag;
        assembly { tag := mload(add(args, 32)) }
        assertEq(tag, EVM_EXTRA_ARGS_V1_TAG, "wrong EVMExtraArgsV1 tag");
    }

    function test_extraArgsContainsGasLimit() public {
        vm.prank(user);
        sender.sendCrossChain{value: 1 ether}(DEST_CHAIN, recipient, address(usdc), 1000e18);

        bytes memory args = router.lastExtraArgs();
        // Layout: 4 bytes tag + 32 bytes abi.encode(gasLimit)
        assertEq(args.length, 36, "extraArgs should be 36 bytes");

        uint256 gasLimit;
        assembly { gasLimit := mload(add(args, 36)) }
        assertEq(gasLimit, 200_000, "gas limit should be 200k");
    }

    // ── CCIP_GAS_LIMIT constant ───────────────────────────────────────────

    function test_ccipGasLimitConstant() public view {
        assertEq(sender.CCIP_GAS_LIMIT(), 200_000);
    }

    // ── Fee estimation accounts for extraArgs ─────────────────────────────

    function test_feeEstimationUsesExtraArgs() public view {
        uint256 fee = sender.estimateFee(DEST_CHAIN, recipient, address(usdc), 100e18);
        // Mock router returns higher fee for non-empty extraArgs
        assertEq(fee, 0.01 ether, "fee should reflect non-empty extraArgs");
    }

    // ── sendCrossChain still works end-to-end ─────────────────────────────

    function test_sendCrossChainHappyPath() public {
        uint256 amount = 1000e18;
        uint256 expectedFee = (amount * 50) / 10_000; // 0.5%
        uint256 expectedNet = amount - expectedFee;

        vm.prank(user);
        sender.sendCrossChain{value: 1 ether}(DEST_CHAIN, recipient, address(usdc), amount);

        assertEq(usdc.balanceOf(treasury), expectedFee, "treasury gets fee");
        assertEq(usdc.balanceOf(address(router)), expectedNet, "router gets net");
    }

    // ── ETH refund works ──────────────────────────────────────────────────

    function test_excessETHRefunded() public {
        uint256 balBefore = user.balance;

        vm.prank(user);
        sender.sendCrossChain{value: 1 ether}(DEST_CHAIN, recipient, address(usdc), 100e18);

        uint256 spent = balBefore - user.balance;
        assertEq(spent, 0.01 ether, "user should only pay the CCIP fee");
    }

    // ── M3: swapAndBridge refund is call-scoped (no stranded-ETH drain) ────

    function _setupTokenOut() internal returns (MockERC20CCIP tokenOut) {
        tokenOut = new MockERC20CCIP("OUT", "OUT");
        vm.prank(owner);
        sender.setTokenAllowed(address(tokenOut), true);
        swapRouter.setTokenOut(address(tokenOut));
        tokenOut.mint(address(swapRouter), 1_000_000e18); // swap pays out tokenOut
    }

    function test_M3_swapAndBridgeDoesNotDrainStrandedETH() public {
        MockERC20CCIP tokenOut = _setupTokenOut();

        // ETH stranded in the contract (refund dust / mistaken sends / overpay).
        uint256 stranded = 5 ether;
        vm.deal(address(sender), stranded);

        uint256 ccipFee = 0.01 ether;   // MockCCIPRouter fee (non-empty extraArgs)
        uint256 leftover = 0.5 ether;
        uint256 userBefore = user.balance;

        vm.prank(user);
        sender.swapAndBridge{value: ccipFee + leftover}(
            address(usdc), address(tokenOut), 1000e18, 1, DEST_CHAIN, recipient
        );

        // User is refunded ONLY their own leftover (pays just the CCIP fee).
        assertEq(userBefore - user.balance, ccipFee, "user pays only the CCIP fee");
        // The stranded ETH is UNTOUCHED — pre-fix it was drained to the caller.
        assertEq(address(sender).balance, stranded, "stranded ETH must stay in contract");
    }

    function test_M3_rescueETH() public {
        uint256 stranded = 3 ether;
        vm.deal(address(sender), stranded);
        uint256 ownerBefore = owner.balance;

        vm.prank(owner);
        sender.rescueETH(payable(owner));

        assertEq(owner.balance - ownerBefore, stranded, "owner recovers stranded ETH");
        assertEq(address(sender).balance, 0, "contract emptied by rescue");
    }

    function test_M3_rescueETH_onlyOwner() public {
        vm.deal(address(sender), 1 ether);
        vm.prank(user);
        vm.expectRevert(); // Ownable: caller is not the owner
        sender.rescueETH(payable(user));
    }

    function test_M3_rescueToken() public {
        usdc.mint(address(sender), 500e18);
        uint256 ownerBefore = usdc.balanceOf(owner);

        vm.prank(owner);
        sender.rescueToken(address(usdc), owner);

        assertEq(usdc.balanceOf(owner) - ownerBefore, 500e18, "owner recovers stranded token");
    }

    function test_M3_rescueToken_onlyOwner() public {
        usdc.mint(address(sender), 100e18);
        vm.prank(user);
        vm.expectRevert();
        sender.rescueToken(address(usdc), user);
    }
}