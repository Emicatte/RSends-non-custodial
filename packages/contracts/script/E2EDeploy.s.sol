// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/RSendsRouter.sol";
import {MockUSDC6, MockUSDT6} from "../test/mocks/E2EMocks.sol";

/// @title E2EDeploy — deploy the full money-path stack to a local Anvil node.
///
/// Deploys RSendsRouter + a 6-decimal permit USDC mock + a 6-decimal no-bool USDT
/// mock, mints balances to the payer, and wires the locked flat fee config for
/// both tokens. Writes the deployed addresses as JSON to $OUT so the Python E2E
/// harness can read them back.
///
/// Env:
///   OWNER         deployer/owner of the router
///   FEE_COLLECTOR address that receives fees
///   PAYER         address minted token balances (the on-chain payer)
///
/// Deployed addresses are read back by the harness from Foundry's own broadcast
/// artifact (broadcast/E2EDeploy.s.sol/<chainId>/run-latest.json) — no extra file
/// write (which Foundry's fs sandbox would block).
///
/// Run:
///   OWNER=0x.. FEE_COLLECTOR=0x.. PAYER=0x.. \
///   forge script script/E2EDeploy.s.sol:E2EDeploy \
///     --rpc-url http://127.0.0.1:8545 --broadcast --private-key <deployerKey>
contract E2EDeploy is Script {
    // Locked flat fee — 6-decimal stablecoins (matches script/SetFeeConfig.s.sol).
    uint256 constant BASE_6      = 600000;        // €0.60
    uint256 constant THRESHOLD_6 = 1000000000;    // €1,000
    uint256 constant SURCHARGE_6 = 2400000;       // €2.40 → at/above fee = 3_000_000 (€3.00)

    // Generous mint so balances never bound the test.
    uint256 constant MINT_6 = 1_000_000 * 1e6;    // 1,000,000 tokens

    function run() external {
        address owner        = vm.envAddress("OWNER");
        address feeCollector = vm.envAddress("FEE_COLLECTOR");
        address payer        = vm.envAddress("PAYER");

        vm.startBroadcast();

        RSendsRouter router = new RSendsRouter(owner, feeCollector);

        MockUSDC6 usdc = new MockUSDC6();
        MockUSDT6 usdt = new MockUSDT6();

        usdc.mint(payer, MINT_6);
        usdt.mint(payer, MINT_6);

        router.setFeeConfig(address(usdc), BASE_6, THRESHOLD_6, SURCHARGE_6, true);
        router.setFeeConfig(address(usdt), BASE_6, THRESHOLD_6, SURCHARGE_6, true);

        vm.stopBroadcast();

        // Addresses also surface in the broadcast artifact; log for debugging.
        console2.log("router", address(router));
        console2.log("usdc", address(usdc));
        console2.log("usdt", address(usdt));
    }
}
