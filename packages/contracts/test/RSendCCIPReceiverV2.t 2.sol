// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/RSendCCIPReceiverV2.sol";

contract MockERC20Recv is IERC20 {
    string  public name   = "USDC";
    string  public symbol = "USDC";
    uint8   public decimals = 6;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

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

contract RSendCCIPReceiverV2Test is Test {
    RSendCCIPReceiverV2 public receiver;
    MockERC20Recv       public usdc;

    address ccipRouter    = makeAddr("ccipRouter");
    address owner         = makeAddr("owner");
    address senderOnSrc   = makeAddr("senderOnSrc");
    address recipient     = makeAddr("recipient");
    uint64  constant SRC_CHAIN = 5009297550715157269; // Ethereum selector

    function setUp() public {
        receiver = new RSendCCIPReceiverV2(ccipRouter, owner);
        usdc     = new MockERC20Recv();

        vm.prank(owner);
        receiver.setAllowedSender(SRC_CHAIN, senderOnSrc);

        // Fund receiver with tokens (simulates CCIP delivering tokens)
        usdc.mint(address(receiver), 10_000e6);
    }

    function _buildMessage(
        address _recipient,
        uint256 _amount
    ) internal view returns (IAny2EVMMessageReceiver.Any2EVMMessage memory) {
        IAny2EVMMessageReceiver.EVMTokenAmount[] memory tokens =
            new IAny2EVMMessageReceiver.EVMTokenAmount[](1);
        tokens[0] = IAny2EVMMessageReceiver.EVMTokenAmount({
            token: address(usdc),
            amount: _amount
        });

        return IAny2EVMMessageReceiver.Any2EVMMessage({
            messageId: keccak256(abi.encode(block.timestamp, _recipient)),
            sourceChainSelector: SRC_CHAIN,
            sender: abi.encode(senderOnSrc),
            data: abi.encode(_recipient),
            destTokenAmounts: tokens
        });
    }

    // ── Zero recipient reverts ────────────────────────────────────────────

    function test_zeroRecipientReverts() public {
        IAny2EVMMessageReceiver.Any2EVMMessage memory msg_ = _buildMessage(address(0), 1000e6);

        vm.prank(ccipRouter);
        vm.expectRevert(ZeroRecipient.selector);
        receiver.ccipReceive(msg_);

        // Tokens stay in receiver, not burned
        assertEq(usdc.balanceOf(address(receiver)), 10_000e6);
        assertEq(usdc.balanceOf(address(0)), 0);
    }

    // ── Valid recipient works ─────────────────────────────────────────────

    function test_validRecipientReceivesTokens() public {
        IAny2EVMMessageReceiver.Any2EVMMessage memory msg_ = _buildMessage(recipient, 500e6);

        vm.prank(ccipRouter);
        receiver.ccipReceive(msg_);

        assertEq(usdc.balanceOf(recipient), 500e6);
        assertEq(usdc.balanceOf(address(receiver)), 9_500e6);
    }

    // ── Only router can call ──────────────────────────────────────────────

    function test_onlyRouterCanCall() public {
        IAny2EVMMessageReceiver.Any2EVMMessage memory msg_ = _buildMessage(recipient, 100e6);

        vm.prank(makeAddr("attacker"));
        vm.expectRevert(OnlyRouter.selector);
        receiver.ccipReceive(msg_);
    }

    // ── Unknown sender reverts ────────────────────────────────────────────

    function test_unknownSenderReverts() public {
        IAny2EVMMessageReceiver.EVMTokenAmount[] memory tokens =
            new IAny2EVMMessageReceiver.EVMTokenAmount[](1);
        tokens[0] = IAny2EVMMessageReceiver.EVMTokenAmount({
            token: address(usdc),
            amount: 100e6
        });

        IAny2EVMMessageReceiver.Any2EVMMessage memory msg_ = IAny2EVMMessageReceiver.Any2EVMMessage({
            messageId: keccak256("unknown"),
            sourceChainSelector: SRC_CHAIN,
            sender: abi.encode(makeAddr("unknown")),
            data: abi.encode(recipient),
            destTokenAmounts: tokens
        });

        vm.prank(ccipRouter);
        vm.expectRevert(UnknownSender.selector);
        receiver.ccipReceive(msg_);
    }

    // ── Idempotency ───────────────────────────────────────────────────────

    function test_duplicateMessageReverts() public {
        IAny2EVMMessageReceiver.Any2EVMMessage memory msg_ = _buildMessage(recipient, 100e6);

        vm.prank(ccipRouter);
        receiver.ccipReceive(msg_);

        vm.prank(ccipRouter);
        vm.expectRevert(AlreadyProcessed.selector);
        receiver.ccipReceive(msg_);
    }
}
