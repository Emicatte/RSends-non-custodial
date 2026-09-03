// SPDX-License-Identifier: MIT
pragma solidity 0.8.36;

import {IERC20}          from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20}       from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

error LengthMismatch();
error BadRecipientCount();
error BpsSumNot10000();
error ZeroRecipient();
error ZeroBps();
error ZeroAmount();
error ZeroToken();
error DuplicateRecipient();
error NoPolicy();
error BelowMinAmount(uint256 amount, uint256 minAmount);

/// RSendsAutoSplit — distribuzione periodica non-custodial del saldo di un
/// wallet merchant dedicato. Il merchant approva UNA volta
/// (token.approve(autoSplit, MAX)) e registra una policy (2..10 destinatari,
/// bps a somma ESATTA 10000, minAmount). executeSplit è permissionless:
/// chiunque (keeper incluso) distribuisce min(balance, allowance) via
/// transferFrom merchant -> recipient[i], tutto-o-niente, e il wallet chiude
/// a saldo ESATTAMENTE zero. Revoca unilaterale: approve(0). Nessun owner,
/// pause, upgrade, delegatecall o call arbitraria: il contratto non detiene
/// mai saldo e nessun ruolo privilegiato esiste.
contract RSendsAutoSplit is ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 public constant MIN_RECIPIENTS = 2;
    uint256 public constant MAX_RECIPIENTS = 10;
    uint256 public constant BPS_DENOMINATOR = 10_000;

    struct Policy {
        address[] recipients;
        uint16[] bps;
        uint256 minAmount;
    }

    mapping(address merchant => mapping(address token => Policy)) private _policies;

    event PolicySet(
        address indexed merchant, address indexed token,
        address[] recipients, uint16[] bps, uint256 minAmount
    );
    event PolicyCleared(address indexed merchant, address indexed token);
    event SplitExecuted(
        address indexed merchant, address indexed token, address indexed caller,
        uint256 totalAmount, address[] recipients, uint256[] amounts, uint256 blockTimestamp
    );

    function setPolicy(address, address[] calldata, uint16[] calldata, uint256) external {}

    function clearPolicy(address) external {}

    function executeSplit(address, address) external nonReentrant {}

    function getPolicy(address merchant, address token)
        external view
        returns (address[] memory recipients, uint16[] memory bps, uint256 minAmount)
    {
        Policy storage p = _policies[merchant][token];
        return (p.recipients, p.bps, p.minAmount);
    }

    function previewSplit(address, address)
        external view
        returns (uint256 total, uint256[] memory amounts)
    {}
}
