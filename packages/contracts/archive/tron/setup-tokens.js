/**
 * Post-deploy: abilita i token principali su Tron
 * Esegui con: tronbox exec setup-tokens.js --network mainnet
 */
const FeeRouterV4Tron = artifacts.require("FeeRouterV4Tron");

// Token Tron Mainnet (indirizzi base58)
const TOKENS = {
  USDT:  'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',   // Tether USDT (TRC-20)
  USDC:  'TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8',   // USD Coin
  USDD:  'TPYmHEhy5n8TCEfYGqW2rPxsghSfzghPDn',   // USDD (Tron stablecoin)
  WTRX:  'TNUC9Qb1rRpS5CbWLmNMxXBjyFoydXjWFR',   // Wrapped TRX
  WBTC:  'TXpw8XeWYeTUd4quDskoUqeQPowRh4jY65',   // Wrapped BTC on Tron
  TUSD:  'TUpMhErZL2fhh4sVNULAbNKLokS4GjC1F4',   // TrueUSD
};

module.exports = async function(callback) {
  try {
    const router = await FeeRouterV4Tron.deployed();
    console.log('Router address:', router.address);

    const tokenAddresses = Object.values(TOKENS);
    const statuses = tokenAddresses.map(() => true);

    console.log(`Enabling ${tokenAddresses.length} tokens...`);
    await router.setTokensAllowed(tokenAddresses, statuses);

    // Verifica
    for (const [symbol, addr] of Object.entries(TOKENS)) {
      const allowed = await router.allowedTokens(addr);
      console.log(`  ${symbol} (${addr}): ${allowed ? '\u2705' : '\u274C'}`);
    }

    console.log('Done!');
    callback();
  } catch (err) {
    console.error('Setup failed:', err);
    callback(err);
  }
};
