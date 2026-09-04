// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// SPIKE ONLY -- not production. Isolates executeSplit's own gas at 3 and 10
// legs so the TRON energy numbers have a same-code EVM reference.
//
// Caveat carried into the report: the token here is a plain OZ ERC20. Real
// USDC/USDT do more per transfer (blacklist check, and for USDT a fee calc),
// so these numbers are a FLOOR, not a model of the Base production cost.

import {Test} from "forge-std/Test.sol";
import "../src/RSendsAutoSplit.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract PlainToken is ERC20 {
    constructor() ERC20("Plain", "PLN") {}
    function mint(address to, uint256 v) external { _mint(to, v); }
    function decimals() public pure override returns (uint8) { return 6; }
}

contract SpikeGasProbe is Test {
    RSendsAutoSplit autoSplit;
    PlainToken token;
    address merchant = address(0xAA01);
    address keeper = address(0xBB02);

    function setUp() public {
        autoSplit = new RSendsAutoSplit();
        token = new PlainToken();
    }

    function _run(uint256 n, bool freshRecipients) internal returns (uint256 gasUsed) {
        address[] memory rec = new address[](n);
        uint16[] memory bps = new uint16[](n);
        uint16 each = uint16(10_000 / n);
        for (uint256 i; i < n; ++i) {
            rec[i] = address(uint160(0x1000 + i * 7 + (freshRecipients ? 0 : 0)));
            bps[i] = each;
        }
        bps[n - 1] = uint16(10_000 - each * (n - 1));

        vm.prank(merchant);
        autoSplit.setPolicy(address(token), rec, bps, 0);

        token.mint(merchant, 1_000_000_000);
        vm.prank(merchant);
        token.approve(address(autoSplit), type(uint256).max);

        vm.prank(keeper);
        uint256 before = gasleft();
        autoSplit.executeSplit(merchant, address(token));
        gasUsed = before - gasleft();
    }

    function test_gas_3_legs() public {
        uint256 g = _run(3, true);
        emit log_named_uint("executeSplit gas, 3 legs (cold recipients)", g);
    }

    function test_gas_10_legs() public {
        uint256 g = _run(10, true);
        emit log_named_uint("executeSplit gas, 10 legs (cold recipients)", g);
    }
}
