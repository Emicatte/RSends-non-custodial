// Measure one executeSplit on NILE.
//   node run.js <legs> <recipientSeed> <label>
// recipientSeed selects the recipient set: reuse a seed to get WARM storage
// slots (recipients already hold USDT), use a fresh seed for COLD ones.
const fs = require('fs');
const path = require('path');
const { client, receipt, summarize, USDT_NILE, TronWeb, KEYDIR } = require('./tron');

const LEGS = parseInt(process.argv[2], 10);
const SEED = process.argv[3];
const LABEL = process.argv[4] || `${LEGS}legs/${SEED}`;
const TOPUP = BigInt(process.argv[5] || '10000000'); // 10 USDT default

function recipients(n, seed) {
  // Deterministic throwaway TRON addresses: 41 || 20 bytes derived from seed.
  const crypto = require('crypto');
  const out = [];
  for (let i = 0; i < n; i++) {
    const h = crypto.createHash('sha256').update(`${seed}:${i}`).digest('hex').slice(0, 40);
    out.push(TronWeb.address.fromHex('41' + h));
  }
  return out;
}

(async () => {
  const tw = client();
  const me = tw.defaultAddress.base58;
  const dep = JSON.parse(fs.readFileSync(path.join(__dirname, 'deployed.json'), 'utf8'));
  const usdt = await tw.contract().at(USDT_NILE);
  const auto = await tw.contract(JSON.parse(fs.readFileSync(path.join(__dirname, 'artifact.json'), 'utf8')).abi, dep.address);

  const rec = recipients(LEGS, SEED);
  const each = Math.floor(10000 / LEGS);
  const bps = Array.from({ length: LEGS }, (_, i) => (i === LEGS - 1 ? 10000 - each * (LEGS - 1) : each));

  // top up the merchant from the reserve (executeSplit drains to zero)
  const rtw = client('nile-reserve.key');
  const rusdt = await rtw.contract().at(USDT_NILE);
  const bal0 = BigInt((await usdt.balanceOf(me).call()).toString());
  if (bal0 < TOPUP) {
    const t = await rusdt.transfer(me, (TOPUP - bal0).toString()).send({ feeLimit: 200e6 });
    await receipt(rtw, t);
  }
  const bal = BigInt((await usdt.balanceOf(me).call()).toString());

  // policy
  const pTx = await auto.setPolicy(USDT_NILE, rec, bps, 0).send({ feeLimit: 300e6 });
  const pInfo = await receipt(tw, pTx);
  const pSum = summarize(`setPolicy ${LEGS} legs`, pInfo);

  // the measurement
  const eTx = await auto.executeSplit(me, USDT_NILE).send({ feeLimit: 900e6 });
  const eInfo = await receipt(tw, eTx);
  const eSum = summarize(LABEL, eInfo);

  const after = BigInt((await usdt.balanceOf(me).call()).toString());
  const result = {
    label: LABEL, contract: dep.address, legs: LEGS, seed: SEED,
    splitAmount: bal.toString(), merchantBalanceAfter: after.toString(),
    zeroBalanceInvariantHeld: after === 0n,
    setPolicy: pSum, executeSplit: eSum,
  };
  const outFile = path.join(__dirname, 'measurements.jsonl');
  fs.appendFileSync(outFile, JSON.stringify(result) + '\n');
  console.log(JSON.stringify(result, null, 2));
})().catch((e) => { console.error('ERROR:', e.message || e); process.exit(1); });
