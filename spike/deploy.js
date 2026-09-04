// Deploy the tv_0.8.31 RSendsAutoSplit artifact to NILE.
const fs = require('fs');
const path = require('path');
const { client, receipt, summarize } = require('./tron');

(async () => {
  const tw = client();
  const me = tw.defaultAddress.base58;
  console.log('deployer:', me);
  const bal = await tw.trx.getBalance(me);
  console.log('TRX balance:', bal / 1e6);

  const art = JSON.parse(fs.readFileSync(path.join(__dirname, 'artifact.json'), 'utf8'));
  console.log('runtime bytes:', art.runtime.length / 2, '| creation bytes:', art.creation.length / 2);

  const tx = await tw.transactionBuilder.createSmartContract({
    abi: art.abi,
    bytecode: art.creation,
    feeLimit: 900_000_000,          // 900 TRX ceiling; actual cost reported below
    callValue: 0,
    userFeePercentage: 100,          // caller pays energy -- measure the true cost
    originEnergyLimit: 10_000_000,
    name: 'RSendsAutoSplit',
    parameters: [],
  }, tw.address.toHex(me));

  const signed = await tw.trx.sign(tx);
  const res = await tw.trx.sendRawTransaction(signed);
  if (!res.result) { console.log('BROADCAST FAILED:', JSON.stringify(res)); process.exit(1); }

  const txid = signed.txID;
  const addr = tw.address.fromHex(tx.contract_address);
  console.log('txid:', txid);
  console.log('contract:', addr);

  const info = await receipt(tw, txid);
  console.log(JSON.stringify(summarize('deploy', info), null, 2));

  fs.writeFileSync(path.join(__dirname, 'deployed.json'),
    JSON.stringify({ address: addr, txid, runtimeBytes: art.runtime.length / 2 }, null, 2));
})().catch((e) => { console.error('ERROR:', e.message || e); process.exit(1); });
