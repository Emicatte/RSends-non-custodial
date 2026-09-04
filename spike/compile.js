// Spike: compile RSendsAutoSplit under tronprotocol solc tv_0.8.31.
// TronBox caps at 0.8.25 (installed) / 0.8.29 (latest), so we drive the wasm
// soljson directly through solc's wrapper -- the same three lines TronBox uses
// internally, minus its maxVersion gate.
const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

const TRONBOX_NM = '/Users/emi/.npm-global/lib/node_modules/tronbox/node_modules';
const wrapper = require(path.join(TRONBOX_NM, 'solc/wrapper'));

const SOLJSON = process.argv[2];
const OZ_LIB = process.argv[3];   // .../lib/openzeppelin-contracts/contracts
const SRC = process.argv[4];
const EVM_VERSION = process.argv[5] || 'cancun';

const soljson = createRequire(__filename)(SOLJSON);
const solc = wrapper(soljson);

console.log('compiler version:', solc.version());

// Resolve @openzeppelin/contracts/... the way foundry's remappings.txt does.
function resolve(importPath) {
  const PREFIX = '@openzeppelin/contracts/';
  if (importPath.startsWith(PREFIX)) {
    return path.join(OZ_LIB, importPath.slice(PREFIX.length));
  }
  return path.resolve(path.dirname(SRC), importPath);
}

const input = {
  language: 'Solidity',
  sources: { 'RSendsAutoSplit.sol': { content: fs.readFileSync(SRC, 'utf8') } },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    viaIR: true,
    evmVersion: EVM_VERSION,
    outputSelection: {
      '*': { '*': ['abi', 'evm.bytecode.object', 'evm.deployedBytecode.object', 'metadata'] },
    },
  },
};

const findImports = (p) => {
  try {
    return { contents: fs.readFileSync(resolve(p), 'utf8') };
  } catch (e) {
    return { error: `not found: ${p} -> ${resolve(p)}` };
  }
};

const out = JSON.parse(solc.compile(JSON.stringify(input), { import: findImports }));

const errors = out.errors || [];
const hard = errors.filter((e) => e.severity === 'error');
const warn = errors.filter((e) => e.severity !== 'error');

console.log(`\n=== diagnostics: ${hard.length} error(s), ${warn.length} warning(s)/info ===`);
for (const e of errors) {
  console.log(`[${e.severity}] ${e.errorCode || '-'} ${e.type}: ${(e.formattedMessage || e.message).trim()}`);
}

if (hard.length) {
  console.log('\nCOMPILE FAILED');
  process.exit(1);
}

const NAME = path.basename(SRC, '.sol');
const c = out.contracts['RSendsAutoSplit.sol'][NAME];
if (!c) {
  console.log('contracts produced:', Object.keys(out.contracts['RSendsAutoSplit.sol']));
  throw new Error(`contract ${NAME} not in output`);
}
const runtime = c.evm.deployedBytecode.object;
const creation = c.evm.bytecode.object;
const outPath = path.join(path.dirname(SRC), '..',
  NAME === 'RSendsAutoSplit' ? 'artifact.json' : `artifact.${NAME}.json`);
fs.writeFileSync(outPath, JSON.stringify({ abi: c.abi, runtime, creation, metadata: c.metadata }, null, 2));
console.log('artifact ->', path.basename(outPath));

const crypto = require('crypto');
// keccak256 is not in node crypto; use the value solc records in metadata plus
// a raw byte count here, and hash separately with a keccak implementation.
console.log('\n=== artifact ===');
console.log('runtime bytes :', runtime.length / 2);
console.log('creation bytes:', creation.length / 2);
console.log('sha256(runtime):', crypto.createHash('sha256').update(Buffer.from(runtime, 'hex')).digest('hex'));
const md = JSON.parse(c.metadata);
console.log('metadata compiler:', md.compiler.version, '| evmVersion:', md.settings.evmVersion, '| viaIR:', md.settings.viaIR);
