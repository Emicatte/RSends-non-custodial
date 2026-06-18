// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";

interface IDistributor {
    function distributeETH(
        address[] calldata recipients,
        uint256[] calldata amounts
    ) external payable;
}

/**
 * @title StressMaxRecipients
 * @notice Gas stress test for RSendBatchDistributor.distributeETH
 *         Generates N deterministic addresses and sends 1000 wei each.
 *         Usage: N_RECIPIENTS=100 forge script script/StressMaxRecipients.s.sol \
 *                  --broadcast --rpc-url $RPC --private-key $PK -vv
 */
contract StressMaxRecipients is Script {
    address constant DISTRIBUTOR = 0x481062Ba5843BbF8BcC7781EF84D42e49D0D77c3;
    uint256 constant AMT_PER_RECIPIENT = 1_000; // 1000 wei each (negligible ETH)

    function run() external {
        uint256 n = vm.envOr("N_RECIPIENTS", uint256(100));

        address[] memory recipients = new address[](n);
        uint256[] memory amounts    = new uint256[](n);

        // Deterministic addresses unique per N to avoid warm-account bias across tests
        for (uint256 i; i < n; ++i) {
            recipients[i] = address(
                uint160(uint256(keccak256(abi.encodePacked("rsend_stress_v1", n, i))))
            );
            amounts[i] = AMT_PER_RECIPIENT;
        }

        // feeBps = 50 → distributable = msg.value * 9950 / 10000
        // need distributable >= sum(amounts) = n * AMT_PER_RECIPIENT
        // msg.value >= n * AMT_PER_RECIPIENT * 10000 / 9950  (ceiling)
        uint256 totalAmt = n * AMT_PER_RECIPIENT;
        uint256 msgValue = (totalAmt * 10_000 + 9_949) / 9_950;

        uint256 deployerKey = vm.envUint("PRIVATE_KEY");

        console.log("=== RSendBatchDistributor Stress Test ===");
        console.log("N recipients:", n);
        console.log("msg.value (wei):", msgValue);
        console.log("Contract:", DISTRIBUTOR);

        vm.startBroadcast(deployerKey);
        IDistributor(DISTRIBUTOR).distributeETH{value: msgValue}(recipients, amounts);
        vm.stopBroadcast();

        console.log("=== DONE ===");
    }
}
