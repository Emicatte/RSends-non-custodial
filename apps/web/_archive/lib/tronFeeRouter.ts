/**
 * Interazione con FeeRouterV4 su Tron via TronLink (window.tronWeb).
 */

const FEE_ROUTER_ABI = [
  // transferWithOracle
  {
    type: 'function', name: 'transferWithOracle', stateMutability: 'nonpayable',
    inputs: [
      { name: '_token', type: 'address' }, { name: '_amount', type: 'uint256' },
      { name: '_recipient', type: 'address' }, { name: '_nonce', type: 'bytes32' },
      { name: '_deadline', type: 'uint256' }, { name: '_oracleSignature', type: 'bytes' },
    ],
    outputs: [],
  },
  // transferTRXWithOracle
  {
    type: 'function', name: 'transferTRXWithOracle', stateMutability: 'payable',
    inputs: [
      { name: '_recipient', type: 'address' }, { name: '_nonce', type: 'bytes32' },
      { name: '_deadline', type: 'uint256' }, { name: '_oracleSignature', type: 'bytes' },
    ],
    outputs: [],
  },
  // swapAndSend
  {
    type: 'function', name: 'swapAndSend', stateMutability: 'nonpayable',
    inputs: [
      { name: 'tokenIn', type: 'address' }, { name: 'tokenOut', type: 'address' },
      { name: 'amountIn', type: 'uint256' }, { name: 'minAmountOut', type: 'uint256' },
      { name: 'recipient', type: 'address' }, { name: 'nonce', type: 'bytes32' },
      { name: 'deadline', type: 'uint256' }, { name: 'oracleSignature', type: 'bytes' },
    ],
    outputs: [],
  },
]

/**
 * Invia TRC-20 tramite FeeRouter su Tron.
 * Apre TronLink per la firma (equivalente di MetaMask).
 */
export async function tronTransferWithOracle(params: {
  feeRouterAddress: string   // base58 Tron address
  token: string              // base58 token address
  amount: string             // in sun (unita' minime)
  recipient: string          // base58 address
  nonce: string              // bytes32 hex
  deadline: number
  oracleSignature: string    // hex signature
}): Promise<string> {
  const tw = (window as any).tronWeb
  if (!tw || !tw.ready) throw new Error('TronLink not connected')

  const contract = await tw.contract(FEE_ROUTER_ABI, params.feeRouterAddress)

  // Questo apre il popup TronLink per approvazione
  const tx = await contract.transferWithOracle(
    params.token,
    params.amount,
    params.recipient,
    params.nonce,
    params.deadline,
    params.oracleSignature,
  ).send()

  return tx // transaction ID
}

/**
 * Invia TRX nativo tramite FeeRouter.
 */
export async function tronTransferTRXWithOracle(params: {
  feeRouterAddress: string
  recipient: string
  amount: string             // in sun
  nonce: string
  deadline: number
  oracleSignature: string
}): Promise<string> {
  const tw = (window as any).tronWeb
  if (!tw || !tw.ready) throw new Error('TronLink not connected')

  const contract = await tw.contract(FEE_ROUTER_ABI, params.feeRouterAddress)

  const tx = await contract.transferTRXWithOracle(
    params.recipient,
    params.nonce,
    params.deadline,
    params.oracleSignature,
  ).send({ callValue: params.amount }) // callValue = TRX in sun

  return tx
}
