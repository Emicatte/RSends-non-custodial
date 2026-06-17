# Deprecated Contracts

## FeeRouterV3.sol — Deprecated, replaced by FeeRouterV4

**Status:** Testnet-only (Base Sepolia, chain 84532). All mainnet chains use FeeRouterV4.

### F-SC-01: Oracle Typehash Missing `sender` (LOW, Unfixed)

**Finding:** `transferWithPermit2(TransferParams p, address sender)` accepts a `sender` parameter, but the EIP-712 `TRANSFER_TYPEHASH` does not include `sender` in the signed struct:

```solidity
// FeeRouterV3.sol — current typehash (missing sender)
bytes32 private constant TRANSFER_TYPEHASH =
    keccak256("TransferParams(address token,uint256 amount,address recipient,uint256 nonce,uint256 deadline)");
```

A relayer could submit a valid oracle signature with a different `sender` address, since `sender` is not covered by the signature.

**Resolution:** Not fixed. FeeRouterV3 is deprecated and only deployed on Base Sepolia testnet. FeeRouterV4 corrects this by including `sender` in its `_ORACLE_TYPEHASH`:

```solidity
// FeeRouterV4.sol — sender included
bytes32 private constant _ORACLE_TYPEHASH = keccak256(
    "OracleApproval(address sender,address recipient,"
    "address tokenIn,address tokenOut,uint256 amountIn,"
    "bytes32 nonce,uint256 deadline)"
);
```

**Action required:** None. Do not deploy FeeRouterV3 to mainnet. If testnet usage must continue, accept the risk or migrate testnet to FeeRouterV4.
