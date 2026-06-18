// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract RSendForwarder is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    struct ForwardingRule {
        address destination1;
        address destination2;
        uint16  splitBps1;
        uint256 minThreshold;
        bool    active;
    }

    mapping(address => ForwardingRule) public rules;
    address[] public registeredSources;
    uint256 public totalForwarded;
    uint256 public totalSplits;

    event RuleCreated(address indexed source, address dest1, address dest2, uint16 splitBps1);
    event RuleUpdated(address indexed source, bool active);
    event Forwarded(address indexed source, address indexed dest, uint256 amount);
    event SplitForwarded(address indexed source, address dest1, uint256 amount1, address dest2, uint256 amount2);
    event EmergencyWithdraw(address indexed to, uint256 amount);

    constructor() Ownable(msg.sender) {}

    function createRule(address source, address dest1, address dest2, uint16 splitBps1, uint256 minWei) external onlyOwner {
        require(dest1 != address(0), "dest1 required");
        require(splitBps1 <= 10000 && splitBps1 > 0, "invalid bps");
        if (dest2 != address(0)) require(splitBps1 < 10000, "split needs bps < 10000");
        if (!rules[source].active && rules[source].destination1 == address(0)) registeredSources.push(source);
        rules[source] = ForwardingRule(dest1, dest2, splitBps1, minWei, true);
        emit RuleCreated(source, dest1, dest2, splitBps1);
    }

    function setRuleActive(address source, bool active) external onlyOwner {
        require(rules[source].destination1 != address(0), "rule not found");
        rules[source].active = active;
        emit RuleUpdated(source, active);
    }

    receive() external payable nonReentrant {
        ForwardingRule storage rule = rules[msg.sender];
        if (!rule.active || rule.destination1 == address(0) || msg.value < rule.minThreshold) return;
        _executeForward(msg.sender, msg.value, rule);
    }

    function manualForward(address source) external onlyOwner nonReentrant {
        ForwardingRule storage rule = rules[source];
        require(rule.active && rule.destination1 != address(0), "no active rule");
        uint256 balance = address(this).balance;
        require(balance >= rule.minThreshold, "below threshold");
        _executeForward(source, balance, rule);
    }

    function forwardERC20(address source, IERC20 token) external onlyOwner nonReentrant {
        ForwardingRule storage rule = rules[source];
        require(rule.active && rule.destination1 != address(0), "no active rule");
        uint256 balance = token.balanceOf(address(this));
        require(balance > 0, "no token balance");
        if (rule.destination2 != address(0) && rule.splitBps1 < 10000) {
            uint256 amount1 = (balance * rule.splitBps1) / 10000;
            uint256 amount2 = balance - amount1;
            token.safeTransfer(rule.destination1, amount1);
            token.safeTransfer(rule.destination2, amount2);
            emit SplitForwarded(source, rule.destination1, amount1, rule.destination2, amount2);
            totalSplits++;
        } else {
            token.safeTransfer(rule.destination1, balance);
            emit Forwarded(source, rule.destination1, balance);
        }
        totalForwarded += balance;
    }

    function _executeForward(address source, uint256 amount, ForwardingRule storage rule) internal {
        if (rule.destination2 != address(0) && rule.splitBps1 < 10000) {
            uint256 amount1 = (amount * rule.splitBps1) / 10000;
            uint256 amount2 = amount - amount1;
            (bool s1,) = rule.destination1.call{value: amount1}("");
            require(s1, "transfer1 failed");
            (bool s2,) = rule.destination2.call{value: amount2}("");
            require(s2, "transfer2 failed");
            emit SplitForwarded(source, rule.destination1, amount1, rule.destination2, amount2);
            totalSplits++;
        } else {
            (bool ok,) = rule.destination1.call{value: amount}("");
            require(ok, "transfer failed");
            emit Forwarded(source, rule.destination1, amount);
        }
        totalForwarded += amount;
    }

    function emergencyWithdraw(address payable to) external onlyOwner {
        uint256 bal = address(this).balance;
        require(bal > 0, "no balance");
        (bool ok,) = to.call{value: bal}("");
        require(ok, "withdraw failed");
        emit EmergencyWithdraw(to, bal);
    }

    function emergencyWithdrawERC20(IERC20 token, address to) external onlyOwner {
        uint256 bal = token.balanceOf(address(this));
        require(bal > 0, "no balance");
        token.safeTransfer(to, bal);
    }

    function getRule(address source) external view returns (address, address, uint16, uint256, bool) {
        ForwardingRule storage r = rules[source];
        return (r.destination1, r.destination2, r.splitBps1, r.minThreshold, r.active);
    }

    function getRegisteredCount() external view returns (uint256) {
        return registeredSources.length;
    }
}
