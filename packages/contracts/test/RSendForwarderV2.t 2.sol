// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/RSendForwarderV2.sol";

contract ForwarderSource {
    function sendETH(address payable to) external payable {
        (bool ok,) = to.call{value: msg.value}("");
        require(ok, "send failed");
    }

    function trySendETH(address payable to) external payable returns (bool) {
        (bool ok,) = to.call{value: msg.value}("");
        return ok;
    }
}

contract RSendForwarderV2Test is Test {
    RSendForwarderV2 public forwarder;
    ForwarderSource  public source;

    address dest1 = makeAddr("dest1");
    address dest2 = makeAddr("dest2");

    function setUp() public {
        forwarder = new RSendForwarderV2();
        source    = new ForwarderSource();
        vm.deal(address(source), 100 ether);
    }

    // ── minThreshold enforcement ──────────────────────────────────────────

    function test_rejectsBelowMinWei() public {
        forwarder.createRule(address(source), dest1, address(0), 10000, 0.01 ether);

        bool ok = source.trySendETH{value: 0.005 ether}(payable(address(forwarder)));
        assertFalse(ok, "should reject below minWei");
        assertEq(dest1.balance, 0);
    }

    function test_forwardsAtExactMinWei() public {
        forwarder.createRule(address(source), dest1, address(0), 10000, 0.01 ether);

        source.sendETH{value: 0.01 ether}(payable(address(forwarder)));

        assertEq(dest1.balance, 0.01 ether);
        assertEq(address(forwarder).balance, 0);
    }

    function test_forwardsAboveMinWei() public {
        forwarder.createRule(address(source), dest1, address(0), 10000, 0.01 ether);

        source.sendETH{value: 1 ether}(payable(address(forwarder)));

        assertEq(dest1.balance, 1 ether);
    }

    function test_zeroMinWeiForwardsEverything() public {
        forwarder.createRule(address(source), dest1, address(0), 10000, 0);

        source.sendETH{value: 1 wei}(payable(address(forwarder)));

        assertEq(dest1.balance, 1 wei);
    }

    // ── No active rule ────────────────────────────────────────────────────

    function test_revertsWithNoRule() public {
        bool ok = source.trySendETH{value: 1 ether}(payable(address(forwarder)));
        assertFalse(ok, "should reject with no rule");
    }

    function test_revertsWhenRuleDeactivated() public {
        forwarder.createRule(address(source), dest1, address(0), 10000, 0);
        forwarder.setRuleActive(address(source), false);

        bool ok = source.trySendETH{value: 1 ether}(payable(address(forwarder)));
        assertFalse(ok, "should reject when deactivated");
    }

    // ── Split forwarding with minWei ──────────────────────────────────────

    function test_splitForwardAboveMinWei() public {
        forwarder.createRule(address(source), dest1, dest2, 7000, 0.1 ether);

        source.sendETH{value: 1 ether}(payable(address(forwarder)));

        assertEq(dest1.balance, 0.7 ether);
        assertEq(dest2.balance, 0.3 ether);
    }

    function test_splitRejectsBelowMinWei() public {
        forwarder.createRule(address(source), dest1, dest2, 7000, 0.1 ether);

        bool ok = source.trySendETH{value: 0.05 ether}(payable(address(forwarder)));
        assertFalse(ok, "should reject split below minWei");
        assertEq(dest1.balance, 0);
        assertEq(dest2.balance, 0);
    }

    // ── Counters update correctly ─────────────────────────────────────────

    function test_totalForwardedUpdates() public {
        forwarder.createRule(address(source), dest1, address(0), 10000, 0);

        source.sendETH{value: 2 ether}(payable(address(forwarder)));
        source.sendETH{value: 3 ether}(payable(address(forwarder)));

        assertEq(forwarder.totalForwarded(), 5 ether);
    }

    // ── ETH not trapped (key behavioral change from V1) ───────────────────

    function test_dustNotTrapped() public {
        forwarder.createRule(address(source), dest1, address(0), 10000, 0.01 ether);

        bool ok = source.trySendETH{value: 0.001 ether}(payable(address(forwarder)));
        assertFalse(ok, "dust send should revert");
        assertEq(address(forwarder).balance, 0, "no ETH trapped in forwarder");
    }
}
