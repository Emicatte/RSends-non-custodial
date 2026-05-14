/**
 * Monitor CCIP CrossChainSwapAndBridge events.
 * Registra ogni bridge per audit trail.
 */

export interface CrossChainEvent {
  messageId: string
  destinationChainSelector: string
  sender: string
  recipient: string
  tokenIn: string
  tokenOut: string
  amountIn: string
  amountOut: string
  netBridged: string
  fee: string
  txHash: string
  sourceChainId: number
  timestamp: number
}

export async function processCrossChainEvent(event: CrossChainEvent): Promise<void> {
  console.log(
    `[CCIP] SwapAndBridge: ${event.sender.slice(0, 10)} → ${event.recipient.slice(0, 10)}, ` +
    `${event.tokenIn.slice(0, 10)} → ${event.tokenOut.slice(0, 10)}, ` +
    `net=${event.netBridged}, fee=${event.fee}, msgId=${event.messageId.slice(0, 10)}`
  )
  // TODO: Salva nel DB (nuova tabella cross_chain_transfers)
  // TODO: Invia webhook al merchant se configurato
}
