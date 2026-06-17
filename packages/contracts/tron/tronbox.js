require('dotenv').config();

module.exports = {
  networks: {
    mainnet: {
      privateKey: process.env.TRON_PRIVATE_KEY,
      fullHost: 'https://api.trongrid.io',
      headers: { 'TRON-PRO-API-KEY': process.env.TRONGRID_API_KEY },
      network_id: '1',
    },
    shasta: {
      privateKey: process.env.TRON_PRIVATE_KEY,
      fullHost: 'https://api.shasta.trongrid.io',
      network_id: '2',
    },
    nile: {
      privateKey: process.env.TRON_PRIVATE_KEY,
      fullHost: 'https://nile.trongrid.io',
      network_id: '3',
    },
  },
  compilers: {
    solc: {
      version: '0.8.24',
      settings: {
        optimizer: { enabled: true, runs: 200 },
      },
    },
  },
};
