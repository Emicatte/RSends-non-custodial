// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/FeeRouterV4.sol";

contract DeployFeeRouterV4 is Script {

    address constant PERMIT2     = 0x000000000022D473030F116dDEE9F6B43aC78BA3;
    address constant SWAP_ROUTER = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;

    address constant WETH_MAINNET = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;
    address constant WETH_BASE    = 0x4200000000000000000000000000000000000006;
    address constant WETH_SEPOLIA = 0x4200000000000000000000000000000000000006;

    // ── CONFIGURAZIONE ─────────────────────────────────────────────────
    address constant TREASURY      = 0x744Ad424bd3BC24838cF8201D1611d7cC828F9b9;
    address constant ORACLE_SIGNER = 0xa61A471FC226a06C681cf2Ec41d2C64a147b4392;
    uint16  constant FEE_BPS       = 50; // 0.5%

    // Token Base Mainnet
    address constant USDC_BASE       = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address constant USDT_BASE       = 0xfdE4C96256153236aF98292015bA958c14714C22;
    address constant EURC_BASE       = 0x60a3e35cC3064fc371f477011b3E9DD2313ec445;
    address constant cbBTC_BASE      = 0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf;
    address constant DEGEN_BASE      = 0x4eDBc9320305298056041910220E3663A92540B6;
    address constant WETH_TOKEN_BASE = 0x4200000000000000000000000000000000000006;

    // Token Ethereum Mainnet
    address constant USDC_ETH       = 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48;
    address constant USDT_ETH       = 0xdAC17F958D2ee523a2206206994597C13D831ec7;
    address constant EURC_ETH       = 0x1aBaEA1f7C830bD89Acc67eC4af516284b1bC33c;
    address constant WBTC_ETH       = 0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599;
    address constant WETH_TOKEN_ETH = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;

    function run() external {
        uint256 deployerKey  = vm.envUint("PRIVATE_KEY");
        address deployerAddr = vm.addr(deployerKey);
        uint256 chainId      = block.chainid;

        console.log("Deployer:", deployerAddr);
        console.log("Chain ID:", chainId);
        console.log("Treasury:", TREASURY);
        console.log("Oracle Signer:", ORACLE_SIGNER);

        vm.startBroadcast(deployerKey);

        address weth;
        if      (chainId == 1)    weth = WETH_MAINNET;
        else if (chainId == 8453) weth = WETH_BASE;
        else                      weth = WETH_SEPOLIA;

        FeeRouterV4 router = new FeeRouterV4(
            PERMIT2,
            TREASURY,
            ORACLE_SIGNER,
            SWAP_ROUTER,
            weth,
            FEE_BPS,
            deployerAddr
        );

        console.log("========================================");
        console.log("FeeRouterV4 deployed:", address(router));
        console.log("========================================");

        address[] memory tokens;
        bool[]    memory allowed;

        if (chainId == 8453) {
            tokens  = new address[](6);
            allowed = new bool[](6);
            tokens[0] = USDC_BASE;       allowed[0] = true;
            tokens[1] = USDT_BASE;       allowed[1] = true;
            tokens[2] = EURC_BASE;       allowed[2] = true;
            tokens[3] = cbBTC_BASE;      allowed[3] = true;
            tokens[4] = DEGEN_BASE;      allowed[4] = true;
            tokens[5] = WETH_TOKEN_BASE; allowed[5] = true;

            router.setPoolFeeOverride(WETH_TOKEN_BASE, USDC_BASE,  500);
            router.setPoolFeeOverride(WETH_TOKEN_BASE, cbBTC_BASE, 3000);
            router.setPoolFeeOverride(USDC_BASE, EURC_BASE, 100);

        } else if (chainId == 1) {
            tokens  = new address[](5);
            allowed = new bool[](5);
            tokens[0] = USDC_ETH;       allowed[0] = true;
            tokens[1] = USDT_ETH;       allowed[1] = true;
            tokens[2] = EURC_ETH;       allowed[2] = true;
            tokens[3] = WBTC_ETH;       allowed[3] = true;
            tokens[4] = WETH_TOKEN_ETH; allowed[4] = true;

            router.setPoolFeeOverride(WETH_TOKEN_ETH, USDC_ETH, 500);
            router.setPoolFeeOverride(WETH_TOKEN_ETH, WBTC_ETH, 3000);
            router.setPoolFeeOverride(USDC_ETH, EURC_ETH, 100);

        } else {
            tokens  = new address[](1);
            allowed = new bool[](1);
            tokens[0] = WETH_SEPOLIA;
            allowed[0] = true;
        }

        router.setTokensAllowed(tokens, allowed);
        console.log("Tokens allowlisted:", tokens.length);

        vm.stopBroadcast();
    }
}