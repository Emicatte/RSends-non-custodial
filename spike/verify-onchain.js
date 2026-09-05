// Verify the DEPLOYED runtimecode against the local artifact, byte for byte.
// wallet/getcontract returns the creation bytecode; wallet/getcontractinfo is
// the endpoint that carries `runtimecode` plus java-tron's own code_hash.
const fs=require('fs'),path=require('path');
const {client,NILE}=require('./tron');
(async()=>{
  const tw=client();
  const dep=JSON.parse(fs.readFileSync(path.join(__dirname,'deployed.json'),'utf8'));
  const art=JSON.parse(fs.readFileSync(path.join(__dirname,'artifact.json'),'utf8'));
  const hex=tw.address.toHex(dep.address);
  const r=await fetch(`${NILE}/wallet/getcontractinfo`,{
    method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({value:hex,visible:false})});
  const info=await r.json();
  const onchain=(info.runtimecode||'').replace(/^0x/,'').toLowerCase();
  const local  =(art.runtime||'').replace(/^0x/,'').toLowerCase();
  console.log('address                 :',dep.address);
  console.log('local artifact runtime  :',local.length/2,'bytes');
  console.log('on-chain runtimecode    :',onchain.length/2,'bytes');
  console.log('java-tron code_hash     : 0x'+(info.contract_state?.code_hash||info.code_hash||'(absent)'));
  console.log('');
  console.log('BYTE-FOR-BYTE IDENTICAL :',onchain===local && onchain.length>0);
  fs.writeFileSync('/tmp/onchain_runtime.hex','0x'+onchain);
})().catch(e=>{console.error('ERROR:',e.message||e);process.exit(1);});
