// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/RSendsRouter.sol";
import {IERC20Metadata} from "@openzeppelin/contracts/token/ERC20/extensions/IERC20Metadata.sol";

/// @title SetFeeConfig — wire the per-chain token policy into a deployed RSendsRouter.
///
/// SINGLE SOURCE OF TRUTH: token addresses, decimals, the flat fee config, and the
/// `enabled` flag are read from the shared registry JSON
/// (services/backend/app/token_registry.json) — the SAME file the backend consumes,
/// so contract config and backend cannot drift.
///
/// Fee model (per token, in the token's smallest unit, NO oracle, NEVER a %):
///   fee = flatFee + (amount >= threshold ? (aboveFee - flatFee) : 0)
///   Decided pricing: €0.60 below €1,000, €3.00 at/above.
///
/// ADDRESS SAFETY (critical): a wrong token address sends funds to the wrong
/// contract. Before enabling ANY token, `verifyAndSet` asserts the token at that
/// address actually returns the expected `symbol()` and `decimals()` on-chain, and
/// REVERTS on any mismatch. A mistyped/wrong address can never be whitelisted.
/// Native (address(0)) entries are skipped — the constructor enables native and it
/// has no `symbol()`.
///
/// TWO-SIDED DISABLE: this script drives the on-chain `enabled` flag FROM the
/// registry, so re-running it makes on-chain state == registry state. Disabling a
/// token requires BOTH `enabled:false` in token_registry.json AND running this
/// script (which calls setFeeConfig(token, enabled=false)). Flipping ONLY the JSON
/// does NOT stop a direct on-chain pay() — the registry off-chain gate and the
/// on-chain whitelist are independent and must both be set.
///
/// Usage (signs with a Foundry keystore account — NO private key in env/CLI):
///   ROUTER_ADDRESS=0x... \
///   forge script script/SetFeeConfig.s.sol:SetFeeConfig \
///     --rpc-url <chain> --account <keystore> --broadcast
/// The keystore account MUST be the router OWNER (setFeeConfig is onlyOwner).
contract SetFeeConfig is Script {
    /// Reverts when the token at `token` doesn't match the registry's expected metadata.
    error TokenMetadataMismatch(address token, string expected, string actual);
    error FeeConfigInvalid(uint256 flatFee, uint256 aboveFee);

    string constant REGISTRY = "../../services/backend/app/token_registry.json";

    function run() external {
        RSendsRouter router = RSendsRouter(vm.envAddress("ROUTER_ADDRESS"));

        string memory json = vm.readFile(REGISTRY);
        string memory chainKey = string.concat("$[\"", vm.toString(block.chainid), "\"]");

        // Symbols listed for this chain in the registry.
        string[] memory symbols = vm.parseJsonStringArray(json, string.concat(chainKey, ".symbols"));

        // Signs with the CLI --account <keystore> (which must be the OWNER).
        vm.startBroadcast();

        for (uint256 i = 0; i < symbols.length; i++) {
            string memory base = string.concat(chainKey, ".tokens.", symbols[i], ".");

            if (vm.parseJsonBool(json, string.concat(base, "native"))) {
                console2.log("skip native:", symbols[i]);
                continue; // native is enabled by the constructor; address(0) has no symbol()
            }

            address token = vm.parseJsonAddress(json, string.concat(base, "address"));
            uint8 decimals = uint8(vm.parseJsonUint(json, string.concat(base, "decimals")));
            uint256 flatFee = vm.parseJsonUint(json, string.concat(base, "flatFee"));
            uint256 threshold = vm.parseJsonUint(json, string.concat(base, "threshold"));
            uint256 aboveFee = vm.parseJsonUint(json, string.concat(base, "aboveFee"));
            bool enabled = vm.parseJsonBool(json, string.concat(base, "enabled"));
            bool verified = vm.parseJsonBool(json, string.concat(base, "verified"));

            console2.log("token", symbols[i]);
            console2.log("  address", token);
            console2.log("  enabled", enabled);
            console2.log("  human-verified address", verified);

            verifyAndSet(router, token, symbols[i], decimals, flatFee, threshold, aboveFee, enabled);
        }

        vm.stopBroadcast();
    }

    /// Verify (when enabling) the token's on-chain metadata matches the registry,
    /// then write the fee config — driving the on-chain `enabled` flag FROM the
    /// registry so on-chain state == registry state (two-sided disable).
    ///
    /// The symbol()/decimals() ADDRESS-SAFETY gate runs ONLY when enabling: a wrong
    /// address can never be *whitelisted*, while *disabling* a token (enabled=false)
    /// is always allowed — even for a placeholder/wrong address — so a bad disabled
    /// entry can't brick the whole deploy. Broadcast-free + `public` for unit tests.
    function verifyAndSet(
        RSendsRouter router,
        address token,
        string memory expectedSymbol,
        uint8 expectedDecimals,
        uint256 flatFee,
        uint256 threshold,
        uint256 aboveFee,
        bool enabled
    ) public {
        if (aboveFee < flatFee) revert FeeConfigInvalid(flatFee, aboveFee);

        if (enabled) {
            // ── ADDRESS SAFETY: never trust the address blindly when enabling ──
            uint8 onchainDecimals = IERC20Metadata(token).decimals();
            if (onchainDecimals != expectedDecimals) {
                revert TokenMetadataMismatch(
                    token,
                    string.concat("decimals=", vm.toString(uint256(expectedDecimals))),
                    string.concat("decimals=", vm.toString(uint256(onchainDecimals)))
                );
            }
            string memory onchainSymbol = IERC20Metadata(token).symbol();
            if (keccak256(bytes(onchainSymbol)) != keccak256(bytes(expectedSymbol))) {
                revert TokenMetadataMismatch(token, expectedSymbol, onchainSymbol);
            }
        }

        // surcharge passed on-chain = aboveFee - flatFee (so quoteFee returns
        // flatFee below threshold and aboveFee at/above — flat, never proportional).
        // Always written — including enabled=false — so flipping the registry to
        // disabled and re-running this script ACTUALLY stops on-chain pay() for it.
        router.setFeeConfig(token, flatFee, threshold, aboveFee - flatFee, enabled);
    }
}
