// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/RSendsSplitRouter.sol";

/// @title DeploySplitRouter — deploy the ownerless, fee-less RSendsSplitRouter.
///
/// Deployed ALONGSIDE the existing RSendsRouter (which stays untouched). The
/// contract has NO constructor args, NO owner, NO pause, NO whitelist and NO
/// fee — there is nothing to configure after deploy. The only post-deploy step
/// is recording the address in the backend env:
///
///   SPLIT_ROUTER_ADDRESSES_JSON={"84532":"0x..."}
///
/// (the /pay checkout receives the address via the backend `onchain` payload —
/// no frontend hardcode).
///
/// Usage (signs with a Foundry keystore account — NO private key in env/CLI):
///   forge script script/DeploySplitRouter.s.sol:DeploySplitRouter \
///     --rpc-url <chain> --account <keystore> --broadcast
contract DeploySplitRouter is Script {
    function run() external {
        vm.startBroadcast();
        RSendsSplitRouter router = new RSendsSplitRouter();
        vm.stopBroadcast();

        console2.log("RSendsSplitRouter deployed at:", address(router));
        console2.log("chain id:", block.chainid);
        console2.log("record in backend env: SPLIT_ROUTER_ADDRESSES_JSON");
    }
}
