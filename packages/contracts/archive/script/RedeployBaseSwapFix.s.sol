// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/FeeRouterV4.sol";

contract RedeployBaseSwapFix is Script {

    address constant PERMIT2       = 0x000000000022D473030F116dDEE9F6B43aC78BA3;
    address constant TREASURY      = 0x744Ad424bd3BC24838cF8201D1611d7cC828F9b9;
    address constant ORACLE_SIGNER = 0x50b593f57A3FE580096216A1cf8ba3aB070f4b85;
    address constant SWAP_ROUTER   = 0x2626664c2603336E57B271c5C0b26F421741e481; // SwapRouter02 BASE
    address constant WETH          = 0x4200000000000000000000000000000000000006;
    uint16  constant FEE_BPS       = 50;


    // Token Base Mainnet
    address constant USDC  = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address constant USDT  = 0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2;
    address constant DAI   = 0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb;
    address constant cbBTC = 0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf;
    address constant EURC  = 0x60a3e35cC3064fc371f477011b3E9DD2313ec445;
    address constant DEGEN = 0x4eDBc9320305298056041910220E3663A92540B6;

    function run() external {
        uint256 deployerKey  = vm.envUint("PRIVATE_KEY");
        address deployerAddr = vm.addr(deployerKey);

        console.log("Deployer:", deployerAddr);

        vm.startBroadcast(deployerKey);

        // Deploy con deployer come owner temporaneo per fare setup
        FeeRouterV4 router = new FeeRouterV4(
            PERMIT2,
            TREASURY,
            ORACLE_SIGNER,
            SWAP_ROUTER,
            WETH,
            FEE_BPS,
            deployerAddr  // owner temporaneo
        );

        console.log("=== FeeRouterV4 REDEPLOYED ===");
        console.log("Address:", address(router));
        console.log("SwapRouter:", address(router.SWAP_ROUTER()));

        // Abilita token
        address[] memory tokens = new address[](7);
        bool[] memory allowed = new bool[](7);
        tokens[0] = USDC;  allowed[0] = true;
        tokens[1] = USDT;  allowed[1] = true;
        tokens[2] = DAI;   allowed[2] = true;
        tokens[3] = WETH;  allowed[3] = true;
        tokens[4] = cbBTC; allowed[4] = true;
        tokens[5] = EURC;  allowed[5] = true;
        tokens[6] = DEGEN; allowed[6] = true;
        router.setTokensAllowed(tokens, allowed);
        console.log("Tokens enabled: 7");

        // Pool fee overrides
        router.setPoolFeeOverride(WETH, USDC,  500);
        router.setPoolFeeOverride(WETH, cbBTC, 3000);
        router.setPoolFeeOverride(USDC, EURC,  100);

        console.log("Owner:", deployerAddr);

        vm.stopBroadcast();
    }
}
