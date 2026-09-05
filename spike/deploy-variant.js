// Deploy the SPIKE-ONLY unbounded variant to NILE and approve it MAX.
// Purpose: MAX_RECIPIENTS is 400 instead of 10, so the CPU-time limit rather
// than the policy cap becomes the binding constraint, which is what task 3
// needs in order to say anything about headroom.
const fs = require('fs');
const path = require('path');
const { client, receipt, summarize, USDT_NILE } = require('./tron');

(async () => {
  const tw = client();
  const me = tw.defaultAddress.base58;
  console.log('TRX before:', (await tw.trx.getBalance(me)) / 1e6);

  const art = JSON.parse(fs.readFileSync(path.join(__dirname, 'artifact.RSendsAutoSplitUnbounded.json'), 'utf8'));
  const tx = await tw.transactionBuilder.createSmartContract({
    abi: art.abi, bytecode: art.creation,
    feeLimit: 300_000_000, callValue: 0,
    userFeePercentage: 100, originEnergyLimit: 10_000_000,
    name: 'RSendsAutoSplitUnbounded', parameters: [],
  }, tw.address.toHex(me));
  const signed = await tw.trx.sign(tx);
  const res = await tw.trx.sendRawTransaction(signed);
  if (!res.result) { console.log('BROADCAST FAILED:', JSON.stringify(res)); process.exit(1); }
  const addr = tw.address.fromHex(tx.contract_address);
  console.log('variant contract:', addr);
  console.log(JSON.stringify(summarize('deploy variant', await receipt(tw, signed.txID)), null, 2));

  fs.writeFileSync(path.join(__dirname, 'deployed-variant.json'),
    JSON.stringify({ address: addr, txid: signed.txID }, null, 2));

  // MAX approve for the variant (the probes.js run left the main contract at 12345)
  const usdt = await tw.contract().at(USDT_NILE);
  const MAX = '0x' + 'f'.repeat(64);
  const t = await usdt.approve(addr, MAX).send({ feeLimit: 100e6 });
  await receipt(tw, t);
  console.log('variant allowance:', (await usdt.allowance(me, addr).call()).toString());
  console.log('TRX after:', (await tw.trx.getBalance(me)) / 1e6);
})().catch((e) => { console.error('ERROR:', e.message || e); process.exit(1); });
