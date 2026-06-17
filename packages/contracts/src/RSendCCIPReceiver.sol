// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * RSendCCIPReceiver — Riceve token cross-chain e distribuisce al recipient.
 *
 * Deploy: 1 per chain destinazione.
 * Solo il CCIP Router puo' chiamare ccipReceive().
 */

import {Ownable}   from "@openzeppelin/contracts/access/Ownable.sol";
import {IERC20}    from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

// ── CCIP receiver interface ───────────────────────────────────────────────
interface IAny2EVMMessageReceiver {
    struct Any2EVMMessage {
        bytes32          messageId;
        uint64           sourceChainSelector;
        bytes            sender;
        bytes            data;
        EVMTokenAmount[] destTokenAmounts;
    }
    struct EVMTokenAmount {
        address token;
        uint256 amount;
    }
}

// ── Custom errors ─────────────────────────────────────────────────────────
error OnlyRouter();
error UnknownSender();
error AlreadyProcessed();

contract RSendCCIPReceiver is Ownable {
    using SafeERC20 for IERC20;

    // ── Immutables ────────────────────────────────────────────────────────
    address public immutable CCIP_ROUTER;

    // ── Storage ───────────────────────────────────────────────────────────
    mapping(uint64  => address) public allowedSenders;  // source chain -> sender contract
    mapping(bytes32 => bool)    public processedMessages;

    // ── Events ────────────────────────────────────────────────────────────
    event CrossChainReceived(
        bytes32 indexed messageId,
        uint64  indexed sourceChainSelector,
        address indexed recipient,
        address token,
        uint256 amount
    );

    // ── Constructor ───────────────────────────────────────────────────────
    constructor(address _ccipRouter, address _owner) Ownable(_owner) {
        CCIP_ROUTER = _ccipRouter;
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ccipReceive — Chiamata dal CCIP Router quando arriva un messaggio
    // ══════════════════════════════════════════════════════════════════════
    function ccipReceive(
        IAny2EVMMessageReceiver.Any2EVMMessage calldata message
    ) external {
        if (msg.sender != CCIP_ROUTER) revert OnlyRouter();

        // Verifica che il sender sia il nostro contratto sulla source chain
        address sender = abi.decode(message.sender, (address));
        if (allowedSenders[message.sourceChainSelector] != sender) revert UnknownSender();

        // Idempotenza
        if (processedMessages[message.messageId]) revert AlreadyProcessed();
        processedMessages[message.messageId] = true;

        // Decodifica il destinatario finale
        address recipient = abi.decode(message.data, (address));

        // Distribuisci tutti i token ricevuti
        for (uint256 i = 0; i < message.destTokenAmounts.length; i++) {
            IERC20(message.destTokenAmounts[i].token).safeTransfer(
                recipient,
                message.destTokenAmounts[i].amount
            );

            emit CrossChainReceived(
                message.messageId,
                message.sourceChainSelector,
                recipient,
                message.destTokenAmounts[i].token,
                message.destTokenAmounts[i].amount
            );
        }
    }

    // CCIP richiede supportsInterface per verificare il supporto
    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return interfaceId == type(IAny2EVMMessageReceiver).interfaceId
            || interfaceId == 0x01ffc9a7; // ERC165
    }

    // ── Owner ─────────────────────────────────────────────────────────────
    function setAllowedSender(uint64 chainSelector, address sender) external onlyOwner {
        allowedSenders[chainSelector] = sender;
    }

    // Emergency: recupera token bloccati
    function rescueTokens(address token, address to, uint256 amount) external onlyOwner {
        IERC20(token).safeTransfer(to, amount);
    }
}
