/**
 * /pay/[intentId] — the hosted checkout (the only surface a payer sees).
 *
 * Server component shell: locale negotiation, the NextIntlClientProvider
 * (pay namespace only) and the generic metadata live in layout.tsx;
 * everything interactive is in the client tree under _components/:
 *
 *   CheckoutClient (wallet stack) → HostedCheckout (orchestrator)
 *     → usePaymentIntent (fetch polling with backoff — no WebSocket)
 *     → useHostedCheckout (wallet flow) → deriveCheckoutStep (pure machine)
 */

import CheckoutClient from './_components/CheckoutClient'

export default function PayIntentPage() {
  return <CheckoutClient />
}
