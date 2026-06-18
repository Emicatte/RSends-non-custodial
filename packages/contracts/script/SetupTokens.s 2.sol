// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/FeeRouterV4.sol";

contract SetupTokens is Script {

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address routerAddr  = vm.envAddress("ROUTER_ADDRESS");
        uint256 chainId     = block.chainid;

        FeeRouterV4 router = FeeRouterV4(payable(routerAddr));

        vm.startBroadcast(deployerKey);

        // ETH nativo (address(0)) è sempre permesso implicitamente

        if (chainId == 1) {
            // Ethereum
            _allow(router, 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48); // USDC
            _allow(router, 0xdAC17F958D2ee523a2206206994597C13D831ec7); // USDT
            _allow(router, 0x1aBaEA1f7C830bD89Acc67eC4af516284b1bC33c); // EURC
            _allow(router, 0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599); // WBTC
            _allow(router, 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2); // WETH
        } else if (chainId == 10) {
            // Optimism
            _allow(router, 0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85); // USDC
            _allow(router, 0x94b008aA00579c1307B0EF2c499aD98a8ce58e58); // USDT
            _allow(router, 0x4200000000000000000000000000000000000006); // WETH
        } else if (chainId == 56) {
            // BNB
            _allow(router, 0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d); // USDC
            _allow(router, 0x55d398326f99059fF775485246999027B3197955); // USDT
            _allow(router, 0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c); // WBNB
        } else if (chainId == 137) {
            // Polygon
            _allow(router, 0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359); // USDC
            _allow(router, 0xc2132D05D31c914a87C6611C10748AEb04B58e8F); // USDT
            _allow(router, 0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270); // WMATIC
        } else if (chainId == 42161) {
            // Arbitrum
            _allow(router, 0xaf88d065e77c8cC2239327C5EDb3A432268e5831); // USDC
            _allow(router, 0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9); // USDT
            _allow(router, 0x82aF49447D8a07e3bd95BD0d56f35241523fBab1); // WETH
            _allow(router, 0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f); // WBTC
        } else if (chainId == 43114) {
            // Avalanche
            _allow(router, 0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E); // USDC
            _allow(router, 0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7); // USDT
            _allow(router, 0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7); // WAVAX
        }

        vm.stopBroadcast();
    }

    function _allow(FeeRouterV4 router, address token) internal {
        router.setTokenAllowed(token, true);
        console.log("Allowed:", token);
    }
}
