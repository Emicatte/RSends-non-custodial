/**
 * Deploy manuale FeeRouterV4Tron via TronWeb.
 * Bypassa TronBox migrate che causa 429 rate limit.
 *
 * Uso: node deploy-manual.js
 */
require('dotenv').config();
const { TronWeb } = require('tronweb');
const fs = require('fs');
const path = require('path');

const PRIVATE_KEY = process.env.TRON_PRIVATE_KEY;
const API_KEY = process.env.TRONGRID_API_KEY;

if (!PRIVATE_KEY) { console.error('TRON_PRIVATE_KEY mancante in .env'); process.exit(1); }

const tronWeb = new TronWeb({
  fullHost: 'https://api.trongrid.io',
  headers: { 'TRON-PRO-API-KEY': API_KEY },
  privateKey: PRIVATE_KEY,
});

// Constructor params
const TREASURY       = 'TLa72Vvk5sKZGmfpaUVX5wRLCThbAd9qzi';
const ORACLE_SIGNER  = 'TR7UeicrVVThn4cy8vpuu9Qo4kCrcVH6jn';
const SUNSWAP_ROUTER = 'TKzxdSv2FZKQrEqkKVgp5DcwEXBEKMg2Ax';
const WTRX           = 'TNUC9Qb1rRpS5CbWLmNMxXBjyFoydXjWFR';
const FEE_BPS        = 50;
const OWNER          = 'T9yjpgUeDA4HGEU7F9f3QUFADvwhBUo2Fz';

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function main() {
  // Leggi ABI e bytecode dal build di TronBox
  const artifactPath = path.join(__dirname, 'build', 'contracts', 'FeeRouterV4Tron.json');
  if (!fs.existsSync(artifactPath)) {
    console.error('Artifact non trovato. Esegui prima: npx tronbox compile');
    process.exit(1);
  }

  const artifact = JSON.parse(fs.readFileSync(artifactPath, 'utf8'));
  const abi = artifact.abi;
  const bytecode = artifact.bytecode;

  const deployer = tronWeb.address.fromPrivateKey(PRIVATE_KEY);
  console.log('Deployer:', deployer);

  // Controlla balance
  await sleep(500);
  const balance = await tronWeb.trx.getBalance(deployer);
  console.log('Balance:', balance / 1e6, 'TRX');

  if (balance < 500_000_000) { // 500 TRX minimo per deploy
    console.error('Balance insufficiente. Servono almeno 500 TRX per il deploy.');
    process.exit(1);
  }

  console.log('\nDeploying FeeRouterV4Tron...');
  console.log('  Treasury:', TREASURY);
  console.log('  Oracle:  ', ORACLE_SIGNER);
  console.log('  Router:  ', SUNSWAP_ROUTER);
  console.log('  WTRX:    ', WTRX);
  console.log('  FeeBps:  ', FEE_BPS);
  console.log('  Owner:   ', OWNER);

  await sleep(1000); // Rate limit buffer

  try {
    const tx = await tronWeb.transactionBuilder.createSmartContract({
      abi,
      bytecode,
      feeLimit: 5_000_000_000, // 5000 TRX max
      callValue: 0,
      parameters: [
        TREASURY,
        ORACLE_SIGNER,
        SUNSWAP_ROUTER,
        WTRX,
        FEE_BPS,
        OWNER,
      ],
    }, deployer);

    await sleep(500);
    const signed = await tronWeb.trx.sign(tx);

    await sleep(1000);
    const result = await tronWeb.trx.sendRawTransaction(signed);

    if (result.result) {
      const contractAddress = tronWeb.address.fromHex(tx.contract_address);
      console.log('\n✅ Deploy riuscito!');
      console.log('TX ID:    ', result.txid);
      console.log('Contract: ', contractAddress);
      console.log('\nAggiungi a .env.local:');
      console.log(`TRON_FEE_ROUTER_MAINNET=${contractAddress}`);
    } else {
      console.error('\n❌ Broadcast fallito:', result);
    }
  } catch (err) {
    console.error('\n❌ Deploy fallito:', err.message || err);
  }
}

main();
