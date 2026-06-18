// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/FeeRouterV3.sol";

contract DeployFeeRouterV3 is Script {
    // ── Token addresses Base Mainnet ───────────────────────────────────────
    address constant USDC  = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address constant USDT  = 0xfdE4C96256153236aF98292015bA958c14714C22;
    address constant cbBTC = 0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf;
    address constant DEGEN = 0x4eDBc9320305298056041910220E3663A92540B6;
    // ── Token addresses Base Sepolia ───────────────────────────────────────
    // Su Sepolia usa gli stessi indirizzi se disponibili, altrimenti mock

    address constant PERMIT2 = 0x000000000022D473030F116dDEE9F6B43aC78BA3;

    function run() external {
        uint256 deployerKey  = vm.envUint("PRIVATE_KEY");
        address deployerAddr = vm.addr(deployerKey);

        vm.startBroadcast(deployerKey);

        FeeRouterV3 router = new FeeRouterV3(
            PERMIT2,       // Permit2 ufficiale Uniswap
            deployerAddr,  // TREASURY_VAULT
            deployerAddr,  // ORACLE_SIGNER (iniziale = deployer, da aggiornare con backend)
            50,            // FEE_BPS = 0.5%
            deployerAddr   // OWNER
        );

        // ── Allowlist token supportati ─────────────────────────────────────
        address[] memory tokens  = new address[](4);
        bool[]    memory allowed = new bool[](4);

        tokens[0] = USDC;  allowed[0] = true;
        tokens[1] = USDT;  allowed[1] = true;
        tokens[2] = cbBTC; allowed[2] = true;
        tokens[3] = DEGEN; allowed[3] = true;

        router.setTokensAllowed(tokens, allowed);

        console.log("FeeRouterV3 deployed at:", address(router));
        console.log("Oracle signer (initial):", deployerAddr);
        console.log("Treasury vault:         ", deployerAddr);
        console.log("Tokens allowed: USDC, USDT, cbBTC, DEGEN");

        vm.stopBroadcast();
    }
}
