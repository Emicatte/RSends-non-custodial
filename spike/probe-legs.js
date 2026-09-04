// Headroom probe against the SPIKE-ONLY unbounded variant on NILE.
//   node probe-legs.js <legs> <seed>
// Reports setPolicy and executeSplit separately, and surfaces receipt.result
// so an OUT_OF_TIME / OUT_OF_ENERGY is visible rather than swallowed.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { client, receipt, summarize, USDT_NILE, TronWeb } = require('./tron');

const LEGS = parseInt(process.argv[2], 10);
const SEED = process.argv[3] || `probe${LEGS}`;
const TOPUP = BigInt(process.argv[4] || '10000000');

(async () => {
  const tw = client();
  const me = tw.defaultAddress.base58;
  const dep = JSON.parse(fs.readFileSync(path.join(__dirname, 'deployed-variant.json'), 'utf8'));
  const art = JSON.parse(fs.readFileSync(path.join(__dirname, 'artifact.RSendsAutoSplitUnbounded.json'), 'utf8'));
  const auto = await tw.contract(art.abi, dep.address);
  const usdt = await tw.contract().at(USDT_NILE);

  const trxBefore = await tw.trx.getBalance(me);
  console.log(`legs=${LEGS}  TRX before: ${trxBefore / 1e6}`);

  const rec = Array.from({ length: LEGS }, (_, i) =>
    TronWeb.address.fromHex('41' + crypto.createHash('sha256').update(`${SEED}:${i}`).digest('hex').slice(0, 40)));
  const each = Math.floor(10000 / LEGS);
  const bps = Array.from({ length: LEGS }, (_, i) => (i === LEGS - 1 ? 10000 - each * (LEGS - 1) : each));

  // top up
  const rtw = client('nile-reserve.key');
  const rusdt = await rtw.contract().at(USDT_NILE);
  const b0 = BigInt((await usdt.balanceOf(me).call()).toString());
  if (b0 < TOPUP) { await receipt(rtw, await rusdt.transfer(me, (TOPUP - b0).toString()).send({ feeLimit: 200e6 })); }

  const pTx = await auto.setPolicy(USDT_NILE, rec, bps, 0).send({ feeLimit: 1_500_000_000 });
  const pSum = summarize(`setPolicy ${LEGS}`, await receipt(tw, pTx));
  console.log('setPolicy    :', pSum.result, pSum.energy_usage_total, 'energy', pSum.trx_cost, 'TRX');
  if (pSum.result !== 'SUCCESS') { console.log(JSON.stringify(pSum, null, 2)); process.exit(0); }

  const eTx = await auto.executeSplit(me, USDT_NILE).send({ feeLimit: 4_000_000_000 });
  const eSum = summarize(`executeSplit ${LEGS}`, await receipt(tw, eTx));
  console.log('executeSplit :', eSum.result, eSum.energy_usage_total, 'energy', eSum.trx_cost, 'TRX');

  const rec2 = { legs: LEGS, seed: SEED, setPolicy: pSum, executeSplit: eSum,
                 merchantAfter: (await usdt.balanceOf(me).call()).toString(),
                 trxAfter: (await tw.trx.getBalance(me)) / 1e6 };
  fs.appendFileSync(path.join(__dirname, 'headroom.jsonl'), JSON.stringify(rec2) + '\n');
  console.log('merchant after:', rec2.merchantAfter, '| TRX after:', rec2.trxAfter);
  if (eSum.result !== 'SUCCESS') console.log(JSON.stringify(eSum, null, 2));
})().catch((e) => { console.error('ERROR:', e.message || e); process.exit(1); });
