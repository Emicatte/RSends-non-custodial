// Task 4: what behaves differently from Base. NILE only.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { client, receipt, summarize, USDT_NILE, TronWeb } = require('./tron');

(async () => {
  const tw = client();
  const me = tw.defaultAddress.base58;
  const dep = JSON.parse(fs.readFileSync(path.join(__dirname, 'deployed.json'), 'utf8'));
  const usdt = await tw.contract().at(USDT_NILE);
  const out = {};

  // ---- 1. USDT surface vs USDC ----
  out.usdt = {
    decimals: (await usdt.decimals().call()).toString(),
    basisPointsRate: (await usdt.basisPointsRate().call()).toString(),
    maximumFee: (await usdt.maximumFee().call()).toString(),
    deprecated: await usdt.deprecated().call(),
    paused: await usdt.paused().call(),
    isBlackListed_merchant: await usdt.isBlackListed(me).call(),
  };

  // ---- 2. approve-zero-reset guard ----
  // Allowance to the AutoSplit is currently MAX (non-zero). Ethereum's
  // TetherToken has require(!((_value != 0) && (allowed[..] != 0))). If TRON's
  // copy carries it, a non-zero -> non-zero approve must FAIL.
  const before = (await usdt.allowance(me, dep.address).call()).toString();
  let guard;
  try {
    const t = await usdt.approve(dep.address, '12345').send({ feeLimit: 100e6 });
    const info = await receipt(tw, t);
    const res = (info.receipt || {}).result;
    const after = (await usdt.allowance(me, dep.address).call()).toString();
    guard = {
      allowanceBefore: before, attempted: '12345',
      txResult: res, allowanceAfter: after,
      guardPresent: res !== 'SUCCESS',
      note: res === 'SUCCESS'
        ? 'non-zero -> non-zero approve SUCCEEDED: no zero-reset guard on this deployment'
        : 'non-zero -> non-zero approve FAILED: zero-reset guard IS present',
    };
  } catch (e) {
    guard = { allowanceBefore: before, error: String(e.message || e), guardPresent: 'threw' };
  }
  out.approveZeroResetGuard = guard;

  // ---- 3. address format round-trip ----
  const sample = TronWeb.address.fromHex('41' + crypto.createHash('sha256').update('coldB:0').digest('hex').slice(0, 40));
  out.addressFormat = {
    base58: sample,
    hex21_0x41: tw.address.toHex(sample),
    evm20: '0x' + tw.address.toHex(sample).slice(2),
    note: 'TRON address = 0x41 || the same 20 bytes an EVM address uses; the contract sees only the 20 bytes',
  };

  // ---- 4. did the split actually land, and exactly? (safeTransferFrom assembly on TVM) ----
  const legs = 10;
  const recips = Array.from({ length: legs }, (_, i) =>
    TronWeb.address.fromHex('41' + crypto.createHash('sha256').update(`coldB:${i}`).digest('hex').slice(0, 40)));
  const bals = [];
  for (const r of recips) bals.push((await usdt.balanceOf(r).call()).toString());
  out.splitLanded = {
    recipients: recips,
    balances: bals,
    // two runs of 10 USDT each at 1000 bps per leg = 1 USDT per leg per run
    expectedAfterTwoRuns: '2000000 per leg (1 USDT x 2 runs)',
    allEqual: new Set(bals).size === 1,
    merchantBalance: (await usdt.balanceOf(me).call()).toString(),
  };

  // ---- 5. policy round-trip through getPolicy ----
  const p = await (await tw.contract(JSON.parse(fs.readFileSync(path.join(__dirname, 'artifact.json'), 'utf8')).abi, dep.address))
    .getPolicy(me, USDT_NILE).call();
  out.getPolicyRoundTrip = {
    recipients: (p.recipients || p[0]).map((h) => tw.address.fromHex(h)),
    bps: (p.bps || p[1]).map((x) => Number(x)),
    minAmount: (p.minAmount || p[2]).toString(),
  };

  console.log(JSON.stringify(out, null, 2));
  fs.writeFileSync(path.join(__dirname, 'probes.json'), JSON.stringify(out, null, 2));
})().catch((e) => { console.error('ERROR:', e.message || e); process.exit(1); });
