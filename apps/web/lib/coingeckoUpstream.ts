/**
 * CoinGecko upstream URL — single source of truth.
 *
 * Server-side proxies (app/api/market, app/api/tokens-market) call
 * this directly with the COINGECKO_API_KEY header. Client code MUST
 * go through /api/market/* and never reference this constant.
 */
export const COINGECKO_UPSTREAM = 'https://api.coingecko.com/api/v3'
