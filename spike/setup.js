// One-time setup for the split measurements on NILE.
//
// executeSplit distributes min(balance, allowance) and drains the merchant to
// zero, so repeated runs need the balance re-supplied. A second throwaway
// "reserve" key holds the USDT and tops the merchant up before each run.
//
// The allowance is set to MAX on purpose: TetherToken skips the allowance
// SSTORE when allowance == MAX_UINT, and MAX is what the production design
// uses. A bounded allowance would add a storage write per leg and inflate the
// numbers relative to the real design.
const fs = require('fs');
const path = require('path');
const { client, receipt, summarize, USDT_NILE, TronWeb, KEYDIR } = require('./tron');

(async () => {
  const tw = client();
  const me = tw.defaultAddress.base58;

  // reserve key
  const rpath = path.join(KEYDIR, 'nile-reserve.key');
  if (!fs.existsSync(rpath)) {
    const acc = await TronWeb.createAccount();
    fs.writeFileSync(rpath, acc.privateKey, { mode: 0o600 });
    fs.writeFileSync(path.join(KEYDIR, 'nile-reserve.address'), acc.address.base58);
    console.log('reserve generated:', acc.address.base58);
  }
  const reserve = fs.readFileSync(path.join(KEYDIR, 'nile-reserve.address'), 'utf8').trim();
  console.log('merchant:', me);
  console.log('reserve :', reserve);

  const usdt = await tw.contract().at(USDT_NILE);

  // 1. fund the reserve with TRX so it can pay energy for top-ups
  const rbal = await tw.trx.getBalance(reserve);
  if (rbal < 40e6) {
    const txid = await tw.trx.sendTransaction(reserve, 60e6);
    console.log('funded reserve 60 TRX:', txid.txid || txid.transaction?.txID);
    await receipt(tw, txid.txid || txid.transaction.txID);
  }

  // 2. park the USDT in the reserve
  const mUsdt = await usdt.balanceOf(me).call();
  console.log('merchant USDT before:', Number(mUsdt) / 1e6);
  if (Number(mUsdt) > 0) {
    const txid = await usdt.transfer(reserve, mUsdt.toString()).send({ feeLimit: 200e6 });
    console.log('moved all USDT to reserve:', txid);
    console.log(JSON.stringify(summarize('usdt transfer merchant->reserve', await receipt(tw, txid)), null, 2));
  }

  // 3. MAX approve to the AutoSplit
  const dep = JSON.parse(fs.readFileSync(path.join(__dirname, 'deployed.json'), 'utf8'));
  const MAX = '0x' + 'f'.repeat(64);
  const cur = await usdt.allowance(me, dep.address).call();
  console.log('current allowance:', cur.toString());
  if (cur.toString() !== BigInt(MAX).toString()) {
    const txid = await usdt.approve(dep.address, MAX).send({ feeLimit: 200e6 });
    console.log('approve(MAX) txid:', txid);
    console.log(JSON.stringify(summarize('approve MAX', await receipt(tw, txid)), null, 2));
  }
  const after = await usdt.allowance(me, dep.address).call();
  console.log('allowance now:', after.toString());
  console.log('is MAX_UINT256:', after.toString() === BigInt(MAX).toString());
})().catch((e) => { console.error('ERROR:', e.message || e); process.exit(1); });
