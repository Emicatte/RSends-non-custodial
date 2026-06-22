// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/RSendCCIPSender.sol";
import "../src/RSendCCIPReceiver.sol";

contract DeployCCIP is Script {
    address constant TREASURY = 0x744ad424Bd3BC24381CF8201D1611D7Cc828f9b9;
    address constant OWNER    = 0x0019ba6753f4a12E29837243323c017F13bBaF0E;

    function run() external {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        uint256 chainId = block.chainid;

        address ccipRouter;
        address swapRouter;
        address weth;

        if (chainId == 8453) {
            ccipRouter = 0x881e3A65B4d4a04dD529061dd0071cf975F58bCD;
            swapRouter = 0x2626664c2603336E57B271c5C0b26F421741e481;
            weth       = 0x4200000000000000000000000000000000000006;
        } else if (chainId == 1) {
            ccipRouter = 0x80226fc0Ee2b096224EeAc085Bb9a8cba1146f7D;
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;
        } else if (chainId == 42161) {
            ccipRouter = 0x141fa059441E0ca23ce184B6A78bafD2A517DdE8;
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0x82aF49447D8a07e3bd95BD0d56f35241523fBab1;
        } else if (chainId == 10) {
            ccipRouter = 0x3206695CaE29952f4b0c22a169725a865bc8Ce0f;
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0x4200000000000000000000000000000000000006;
        } else if (chainId == 137) {
            ccipRouter = 0x849c5ED5a80F5B408Dd4969b78c2C8fdf0565Bfe;
            swapRouter = 0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
            weth       = 0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270;
        } else if (chainId == 56) {
            ccipRouter = 0x34B03Cb9086d7D758AC55af71584F81A598759FE;
            swapRouter = 0xB971eF87ede563556b2ED4b1C0b0019111Dd85d2;
            weth       = 0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c;
        } else if (chainId == 43114) {
            ccipRouter = 0xF4c7E640EdA248ef95972845a62bdC74237805dB;
            swapRouter = 0xbb00FF08d01D300023C629E8fFfFcb65A5a578cE;
            weth       = 0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7;
        } else {
            revert("Unsupported chain");
        }

        vm.startBroadcast(deployerKey);

        RSendCCIPSender sender = new RSendCCIPSender(
            ccipRouter, TREASURY, swapRouter, weth, OWNER
        );
        RSendCCIPReceiver receiver = new RSendCCIPReceiver(ccipRouter, OWNER);

        console.log("=== CCIP DEPLOYED ===");
        console.log("Chain:", chainId);
        console.log("Sender:", address(sender));
        console.log("Receiver:", address(receiver));

        vm.stopBroadcast();
    }
}
