// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC20}       from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC20Permit} from "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";

/*//////////////////////////////////////////////////////////////
        E2E MOCK TOKENS — 6-decimal stablecoin look-alikes
//////////////////////////////////////////////////////////////
  Deployable mocks for the local-Anvil end-to-end harness. They mirror the
  test-only mocks in test/RSendsRouter.t.sol (MockERC20Permit, MockUSDTNoReturn)
  but with decimals() == 6 so they match the backend token registry (USDC/USDT
  are 6-decimal) and the fee config in minimal units.

  These are TEST artifacts only — never deployed to a real network.
//////////////////////////////////////////////////////////////*/

/// USDC look-alike: standard EIP-2612 permit, 6 decimals (OZ domain version "1").
contract MockUSDC6 is ERC20, ERC20Permit {
    constructor() ERC20("Mock USDC", "mUSDC") ERC20Permit("Mock USDC") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}

/// USDT look-alike: transfer/transferFrom/approve return NOTHING (must work via
/// SafeERC20), 6 decimals, NO permit. Mirrors MockUSDTNoReturn from the unit tests.
contract MockUSDT6 {
    string public constant name = "Mock USDT";
    string public constant symbol = "mUSDT";
    uint8 public constant decimals = 6;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external {
        allowance[msg.sender][spender] = amount; // no return value
    }

    function transfer(address to, uint256 amount) external {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount; // no return value
    }

    function transferFrom(address from, address to, uint256 amount) external {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount; // no return value
    }
}
