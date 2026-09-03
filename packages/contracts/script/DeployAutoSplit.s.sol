// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/RSendsAutoSplit.sol";

/// @title DeployAutoSplit — deploy the ownerless RSendsAutoSplit.
///
/// Deployed ALONGSIDE the existing routers (which stay untouched). The
/// contract has NO constructor args, NO owner, NO pause and NO whitelist —
/// there is nothing to configure after deploy. Merchants register their own
/// policies with setPolicy() and arm the contract with a one-time
/// token.approve(autoSplit, MAX) from the dedicated receiving wallet.
///
/// The only post-deploy step is recording the address in the backend env
/// (new var, same shape as the router maps):
///
///   AUTO_SPLIT_ADDRESSES_JSON={"84532":"0x..."}
///
/// NEVER add this address to RSENDS_ROUTER_*_ADDRESSES_JSON — the indexer
/// would filter its logs in and then drop them with a WARNING per execution.
///
/// Usage (signs with a Foundry keystore account — NO private key in env/CLI):
///   forge script script/DeployAutoSplit.s.sol:DeployAutoSplit \
///     --rpc-url <chain> --account <keystore> --broadcast
contract DeployAutoSplit is Script {
    function run() external {
        vm.startBroadcast();
        RSendsAutoSplit autoSplit = new RSendsAutoSplit();
        vm.stopBroadcast();

        console2.log("RSendsAutoSplit deployed at:", address(autoSplit));
        console2.log("chain id:", block.chainid);
        console2.log("record in backend env: AUTO_SPLIT_ADDRESSES_JSON");
    }
}
