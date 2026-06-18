const FeeRouterV4Tron = artifacts.require("FeeRouterV4Tron");

// Tron addresses (base58 → hex conversion handled by TronBox)
const TREASURY       = 'TLa72Vvk5sKZGmfpaUVX5wRLCThbAd9qzi';  // 0x744ad424Bd3BC24381CF8201D1611D7Cc828f9b9
const ORACLE_SIGNER  = 'TR7UeicrVVThn4cy8vpuu9Qo4kCrcVH6jn';   // 0xa61A471FC226a06C681cf2Ec41d2C64a147b4392
const OWNER          = 'T9yjpgUeDA4HGEU7F9f3QUFADvwhBUo2Fz';   // 0x0019ba6753f4a12E29837243323c017F13bBaF0E

// SunSwap V2 Router — Mainnet
const SUNSWAP_ROUTER = 'TKzxdSv2FZKQrEqkKVgp5DcwEXBEKMg2Ax';

// WTRX — Wrapped TRX
const WTRX           = 'TNUC9Qb1rRpS5CbWLmNMxXBjyFoydXjWFR';

const FEE_BPS = 50; // 0.5%

module.exports = function(deployer, network) {
  deployer.deploy(
    FeeRouterV4Tron,
    TREASURY,
    ORACLE_SIGNER,
    SUNSWAP_ROUTER,
    WTRX,
    FEE_BPS,
    OWNER,
  ).then(instance => {
    console.log('FeeRouterV4Tron deployed at:', instance.address);
  });
};
