// ON-CHAIN proof that setPolicy rejects the merchant as its own recipient.
//   node selfrecipient-probe.js [position]
// Broadcasts a REAL transaction (not a constant call) so the revert is on the
// ledger with a txid, then decodes the revert data from the receipt.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {client,receipt,summarize,USDT_NILE,TronWeb,NILE}=require('./tron');

const POS=parseInt(process.argv[2]||'1',10);      // which leg becomes the merchant
const SEL_SELF='952612f5', SEL_DUP='56384ae8';

(async()=>{
  const tw=client();
  const me=tw.defaultAddress.base58;
  const dep=JSON.parse(fs.readFileSync(path.join(__dirname,'deployed.json'),'utf8'));

  const rec=Array.from({length:3},(_,i)=>
    TronWeb.address.fromHex('41'+crypto.createHash('sha256').update(`selfprobe:${i}`).digest('hex').slice(0,40)));
  rec[POS]=me;                                     // <-- the merchant pays itself
  const bps=[5000,3000,2000];
  console.log('merchant       :',me);
  console.log('recipients     :',rec.map((a,i)=>i===POS?`${a}  <-- MERCHANT`:a).join('\n                 '));

  const J=(v)=>JSON.stringify(v,(k,x)=>typeof x==="bigint"?x.toString():x);
  const policyBefore=J(await (await tw.contract(
    JSON.parse(fs.readFileSync(path.join(__dirname,'artifact.json'),'utf8')).abi,dep.address))
    .getPolicy(me,USDT_NILE).call());

  const params=[{type:'address',value:USDT_NILE},{type:'address[]',value:rec},
                {type:'uint16[]',value:bps},{type:'uint256',value:0}];
  const built=await tw.transactionBuilder.triggerSmartContract(
    tw.address.toHex(dep.address),'setPolicy(address,address[],uint16[],uint256)',
    {feeLimit:300e6},params,tw.address.toHex(me));
  const signed=await tw.trx.sign(built.transaction);
  const res=await tw.trx.sendRawTransaction(signed);
  if(!res.result){console.log('BROADCAST FAILED:',JSON.stringify(res));process.exit(1);}
  const txid=signed.txID;
  console.log('\nbroadcast txid :',txid);

  const info=await receipt(tw,txid);
  const s=summarize(`setPolicy self-recipient @${POS}`,info);
  const revertHex=(info.contractResult&&info.contractResult[0])||'';
  const sel=revertHex.slice(0,8).toLowerCase();

  console.log('\n=== receipt ===');
  console.log('result             :',s.result);
  console.log('energy_usage_total :',s.energy_usage_total);
  console.log('trx_cost           :',s.trx_cost);
  console.log('blockNumber        :',s.blockNumber);
  console.log('revert data        : 0x'+revertHex);
  console.log('');
  console.log('selector == SelfRecipient()      (0x'+SEL_SELF+') :',sel===SEL_SELF);
  console.log('selector == DuplicateRecipient() (0x'+SEL_DUP +') :',sel===SEL_DUP);

  const policyAfter=J(await (await tw.contract(
    JSON.parse(fs.readFileSync(path.join(__dirname,'artifact.json'),'utf8')).abi,dep.address))
    .getPolicy(me,USDT_NILE).call());
  console.log('policy unchanged by the rejected call :',policyBefore===policyAfter);

  fs.appendFileSync(path.join(__dirname,'measurements.jsonl'),JSON.stringify({
    label:`selfRecipient-revert-pos${POS}`,contract:dep.address,position:POS,recipients:rec,
    txid,result:s.result,revertData:'0x'+revertHex,
    isSelfRecipient:sel===SEL_SELF,isDuplicateRecipient:sel===SEL_DUP,
    policyUnchanged:policyBefore===policyAfter,setPolicy:s})+'\n');
})().catch(e=>{console.error('ERROR:',e.message||e);process.exit(1);});
