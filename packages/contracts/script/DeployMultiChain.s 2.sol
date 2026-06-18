// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/FeeRouterV4.sol";

contract DeployMultiChain is Script {

    // ── Costanti (uguali su tutte le chain) ──
    address constant PERMIT2        = 0x000000000022D473030F116dDEE9F6B43aC78BA3;
    address constant TREASURY       = 0x744ad424Bd3BC24381CF8201D1611D7Cc828f9b9;
    address constant ORACLE_SIGNER  = 0xa61A471FC226a06C681cf2Ec41d2C64a147b4392;
    address constant OWNER          = 0x0019ba6753f4a12E29837243323c017F13bBaF0E;
    uint16  constant FEE_BPS        = 50; // 0.5%

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        uint256 chainId = block.chainid;

        // ── Parametri chain-specifici ──
        address swapRouter;
        address weth;

        if (chainId == 1) {
            // Ethereum Mainnet
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;
        } else if (chainId == 10) {
            // Optimism
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0x4200000000000000000000000000000000000006;
        } else if (chainId == 56) {
            // BNB Chain — PancakeSwap V3 SmartRouter
            swapRouter = 0xB971eF87ede563556b2ED4b1C0b0019111Dd85d2;
            weth       = 0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c;
        } else if (chainId == 137) {
            // Polygon
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270;
        } else if (chainId == 42161) {
            // Arbitrum
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0x82aF49447D8a07e3bd95BD0d56f35241523fBab1;
        } else if (chainId == 43114) {
            // Avalanche — Uniswap V3 on Avalanche
            swapRouter = 0xbb00FF08d01D300023C629E8fFfFcb65A5a578cE;
            weth       = 0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7;
        } else if (chainId == 8453) {
            // Base
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0x4200000000000000000000000000000000000006;
        } else {
            revert("Unsupported chain");
        }

        vm.startBroadcast(deployerKey);

        FeeRouterV4 router = new FeeRouterV4(
            PERMIT2,
            TREASURY,
            ORACLE_SIGNER,
            swapRouter,
            weth,
            FEE_BPS,
            OWNER
        );

        console.log("FeeRouterV4 deployed at:", address(router));
        console.log("Chain ID:", chainId);
        console.log("WETH:", weth);
        console.log("SwapRouter:", swapRouter);

        vm.stopBroadcast();
    }
}
