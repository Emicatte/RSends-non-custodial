// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import "../src/RSendsRouter.sol";
import {SetFeeConfig} from "../script/SetFeeConfig.s.sol";
import {MockUSDC6} from "./mocks/E2EMocks.sol";

/// Tests the ADDRESS-SAFETY gate of the token-policy wiring: verifyAndSet must
/// assert the token's on-chain symbol()+decimals() before enabling, and REVERT on
/// any mismatch — so a wrong/mistyped address can never be whitelisted.
contract SetFeeConfigTest is Test {
    // 6-decimal decided pricing (€0.60 / €3.00 at/above €1,000).
    uint256 constant FLAT_6      = 600_000;        // €0.60
    uint256 constant THRESHOLD_6 = 1_000_000_000;  // €1,000
    uint256 constant ABOVE_6     = 3_000_000;      // €3.00
    uint256 constant SURCHARGE_6 = ABOVE_6 - FLAT_6;

    SetFeeConfig internal cfg;
    RSendsRouter internal router;
    MockUSDC6 internal token;
    address internal feeCollector = makeAddr("feeCollector");

    function setUp() public {
        cfg = new SetFeeConfig();
        // Router owned by the SetFeeConfig instance so its inner setFeeConfig call
        // (onlyOwner) succeeds when invoked from verifyAndSet.
        router = new RSendsRouter(address(cfg), feeCollector);
        token = new MockUSDC6(); // symbol "mUSDC", decimals 6
    }

    function test_verifyAndSet_appliesFeeConfig_onMatch() public {
        cfg.verifyAndSet(router, address(token), "mUSDC", 6, FLAT_6, THRESHOLD_6, ABOVE_6, true);

        (uint256 baseFee, uint256 threshold, uint256 surcharge, bool enabled) =
            router.feeConfig(address(token));
        assertEq(baseFee, FLAT_6, "baseFee");
        assertEq(threshold, THRESHOLD_6, "threshold");
        assertEq(surcharge, SURCHARGE_6, "surcharge");
        assertTrue(enabled, "enabled");

        // Flat fee, never proportional: same aboveFee for any amount >= threshold.
        assertEq(router.quoteFee(address(token), THRESHOLD_6 - 1), FLAT_6);
        assertEq(router.quoteFee(address(token), THRESHOLD_6), ABOVE_6);
        assertEq(router.quoteFee(address(token), THRESHOLD_6 * 5000), ABOVE_6);
    }

    function test_verifyAndSet_revertsOnSymbolMismatch() public {
        // Token actually returns "mUSDC"; registry claims "USDC" → must revert.
        vm.expectRevert(
            abi.encodeWithSelector(
                SetFeeConfig.TokenMetadataMismatch.selector, address(token), "USDC", "mUSDC"
            )
        );
        cfg.verifyAndSet(router, address(token), "USDC", 6, FLAT_6, THRESHOLD_6, ABOVE_6, true);
    }

    function test_verifyAndSet_revertsOnDecimalsMismatch() public {
        // Token has 6 decimals; registry claims 18 → must revert before any enable.
        vm.expectRevert(
            abi.encodeWithSelector(
                SetFeeConfig.TokenMetadataMismatch.selector, address(token), "decimals=18", "decimals=6"
            )
        );
        cfg.verifyAndSet(router, address(token), "mUSDC", 18, FLAT_6, THRESHOLD_6, ABOVE_6, true);

        // And the token was never enabled.
        (,,, bool enabled) = router.feeConfig(address(token));
        assertFalse(enabled, "must not enable on mismatch");
    }

    /// Proves the shared registry JSON is readable (fs_permissions) and the exact
    /// bracket-path syntax run() uses resolves — incl. big 18-dec integers.
    function test_registryJson_readable_andParses() public view {
        string memory json = vm.readFile("../../services/backend/app/token_registry.json");
        string memory baseKey = "$[\"8453\"]";
        string[] memory symbols = vm.parseJsonStringArray(json, string.concat(baseKey, ".symbols"));
        assertGt(symbols.length, 0, "base has symbols");

        address usdc = vm.parseJsonAddress(json, string.concat(baseKey, ".tokens.USDC.address"));
        assertEq(usdc, 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913, "base USDC address");
        assertEq(vm.parseJsonUint(json, string.concat(baseKey, ".tokens.USDC.decimals")), 6);
        assertEq(vm.parseJsonUint(json, string.concat(baseKey, ".tokens.USDC.flatFee")), 600_000);
        assertEq(vm.parseJsonUint(json, string.concat(baseKey, ".tokens.USDC.aboveFee")), 3_000_000);

        // 18-decimal big integers parse exactly.
        string memory ethKey = "$[\"1\"]";
        assertEq(
            vm.parseJsonUint(json, string.concat(ethKey, ".tokens.DAI.threshold")),
            1_000_000_000_000_000_000_000
        );
        assertEq(
            vm.parseJsonUint(json, string.concat(ethKey, ".tokens.DAI.aboveFee")),
            3_000_000_000_000_000_000
        );
    }

    function test_verifyAndSet_disabled_skipsMetadataGate_andWritesDisabled() public {
        // Two-sided disable: disabling must work even with a MISMATCHED symbol/decimals
        // (e.g. a placeholder address) so a bad disabled entry can't brick the deploy,
        // and it must still drive the on-chain enabled flag to false.
        cfg.verifyAndSet(router, address(token), "WRONG", 18, FLAT_6, THRESHOLD_6, ABOVE_6, false);

        (uint256 baseFee, uint256 threshold, uint256 surcharge, bool enabled) =
            router.feeConfig(address(token));
        assertFalse(enabled, "must be disabled on-chain");
        assertEq(baseFee, FLAT_6);
        assertEq(threshold, THRESHOLD_6);
        assertEq(surcharge, SURCHARGE_6);
    }

    function test_verifyAndSet_revertsOnInvalidFee() public {
        vm.expectRevert(
            abi.encodeWithSelector(SetFeeConfig.FeeConfigInvalid.selector, ABOVE_6, FLAT_6)
        );
        // aboveFee < flatFee → invalid.
        cfg.verifyAndSet(router, address(token), "mUSDC", 6, ABOVE_6, THRESHOLD_6, FLAT_6, true);
    }
}
