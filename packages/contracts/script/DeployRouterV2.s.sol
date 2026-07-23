// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/RSendsRouterV2.sol";

/// @title DeployRouterV2 — deploy the ownerless, fee-less RSendsRouterV2.
///
/// Deployed ALONGSIDE the existing RSendsRouter (testnet, which stays
/// untouched). The contract has NO constructor args, NO owner, NO pause, NO
/// whitelist and NO fee — there is nothing to configure after deploy and
/// script/SetFeeConfig.s.sol must NEVER be pointed at it. The only post-deploy
/// step is recording the address in the backend env:
///
///   RSENDS_ROUTER_V2_ADDRESSES_JSON={"8453":"0x..."}
///
/// (the /pay checkout receives the address via the backend `onchain` payload —
/// no frontend hardcode).
///
/// Usage (signs with a Foundry keystore account — NO private key in env/CLI):
///   forge script script/DeployRouterV2.s.sol:DeployRouterV2 \
///     --rpc-url <chain> --account <keystore> --broadcast
contract DeployRouterV2 is Script {
    function run() external {
        vm.startBroadcast();
        RSendsRouterV2 router = new RSendsRouterV2();
        vm.stopBroadcast();

        console2.log("RSendsRouterV2 deployed at:", address(router));
        console2.log("chain id:", block.chainid);
        console2.log("record in backend env: RSENDS_ROUTER_V2_ADDRESSES_JSON");
    }
}
