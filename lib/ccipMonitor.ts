/**
 * Monitor CCIP CrossChainSwapAndBridge events.
 * Registra ogni bridge per audit trail.
 *
 * Gated by NEXT_PUBLIC_FEATURE_CROSSCHAIN: when not "true", the monitor
 * is a no-op and logs a single warning. The TODO paths below MUST be
 * resolved (DB persistence + merchant webhook) before flipping the flag
 * to "true" in production.
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

let disabledWarned = false

export async function processCrossChainEvent(event: CrossChainEvent): Promise<void> {
  if (process.env.NEXT_PUBLIC_FEATURE_CROSSCHAIN !== 'true') {
    if (!disabledWarned) {
      console.warn('[ccipMonitor] disabled: FEATURE_CROSSCHAIN=false')
      disabledWarned = true
    }
    return
  }

  console.log(
    `[CCIP] SwapAndBridge: ${event.sender.slice(0, 10)} → ${event.recipient.slice(0, 10)}, ` +
    `${event.tokenIn.slice(0, 10)} → ${event.tokenOut.slice(0, 10)}, ` +
    `net=${event.netBridged}, fee=${event.fee}, msgId=${event.messageId.slice(0, 10)}`
  )
  // TODO: Salva nel DB (nuova tabella cross_chain_transfers)
  // TODO: Invia webhook al merchant se configurato
}
