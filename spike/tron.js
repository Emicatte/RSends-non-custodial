// Shared Nile helpers for the spike. Nile only -- the host is hardcoded and
// there is no mainnet branch anywhere in this file.
const fs = require('fs');
const path = require('path');

const NILE = 'https://nile.trongrid.io';
const KEYDIR = '/private/tmp/claude-501/-Users-emi-dev-rsends-noncustodial/c00f1066-8cae-4503-9f25-b7f6af8ac301/scratchpad/tron-key';
const TRONWEB = '/Users/emi/.npm-global/lib/node_modules/tronbox/node_modules/tronweb';

const TW = require(TRONWEB);
const TronWeb = TW.TronWeb || TW.default || TW;

const USDT_NILE = 'TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf';

function client(keyfile = 'nile-spike.key') {
  const pk = fs.readFileSync(path.join(KEYDIR, keyfile), 'utf8').trim();
  return new TronWeb({ fullHost: NILE, privateKey: pk });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Poll for the receipt. TRON needs ~3s/block plus solidity-node lag.
async function receipt(tw, txid, tries = 40) {
  for (let i = 0; i < tries; i++) {
    await sleep(3000);
    const info = await tw.trx.getTransactionInfo(txid);
    if (info && info.id) return info;
  }
  throw new Error(`no receipt for ${txid} after ${tries} tries`);
}

function summarize(label, info) {
  const r = info.receipt || {};
  const out = {
    label,
    txid: info.id,
    result: r.result || '(none)',
    energy_usage_total: r.energy_usage_total || 0,
    energy_usage: r.energy_usage || 0,
    energy_fee_sun: r.energy_fee || 0,
    energy_penalty_total: r.energy_penalty_total || 0,
    net_usage: r.net_usage || 0,
    net_fee_sun: r.net_fee || 0,
    fee_sun: info.fee || 0,
    trx_cost: (info.fee || 0) / 1e6,
    blockNumber: info.blockNumber,
  };
  if (info.resMessage) {
    try { out.resMessage = Buffer.from(info.resMessage, 'hex').toString(); } catch { out.resMessage = info.resMessage; }
  }
  return out;
}

module.exports = { NILE, KEYDIR, USDT_NILE, TronWeb, client, receipt, summarize, sleep };
