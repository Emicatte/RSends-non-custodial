/**
 * src/constants/addresses.ts — Known contract addresses per chain
 *
 * Canonical deployment addresses for Uniswap V3, WBTC, Multicall3, etc.
 * across all supported EVM chains.
 */

import type { SupportedChainId } from '../types/chain';

/** Zero address constant */
export const ZERO_ADDRESS: `0x${string}` = '0x0000000000000000000000000000000000000000';

/** Native ETH placeholder address (used by some protocols) */
export const NATIVE_ADDRESS: `0x${string}` = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE';

/** Per-chain contract addresses */
export const CONTRACT_ADDRESSES: Record<SupportedChainId, {
  uniswapV3Router: `0x${string}`;
  uniswapV3Quoter: `0x${string}`;
  uniswapV3Factory: `0x${string}`;
  multicall3: `0x${string}`;
  weth: `0x${string}`;
  wbtc: `0x${string}` | null;
}> = {
  // ── Ethereum Mainnet (1) ────────────────────────────────────
  1: {
    uniswapV3Router:  '0xE592427A0AEce92De3Edee1F18E0157C05861564',
    uniswapV3Quoter:  '0x61fFE014bA17989E743c5F6cB21bF9697530B21e',
    uniswapV3Factory: '0x1F98431c8aD98523631AE4a59f267346ea31F984',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
    wbtc:             '0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599',
  },
  // ── Optimism (10) ───────────────────────────────────────────
  10: {
    uniswapV3Router:  '0xE592427A0AEce92De3Edee1F18E0157C05861564',
    uniswapV3Quoter:  '0x61fFE014bA17989E743c5F6cB21bF9697530B21e',
    uniswapV3Factory: '0x1F98431c8aD98523631AE4a59f267346ea31F984',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0x4200000000000000000000000000000000000006',
    wbtc:             '0x68f180fcCe6836688e9084f035309E29Bf0A2095',
  },
  // ── BNB Chain (56) ──────────────────────────────────────────
  56: {
    uniswapV3Router:  '0xB971eF87ede563556b2ED4b1C0b0019111Dd85d2',
    uniswapV3Quoter:  '0x78D78E420Da98ad378D7799bE8f4AF69033EB077',
    uniswapV3Factory: '0xdB1d10011AD0Ff90774D0C6Bb92e5C5c8b4461F7',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c', // WBNB
    wbtc:             '0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c', // BTCB
  },
  // ── Polygon (137) ───────────────────────────────────────────
  137: {
    uniswapV3Router:  '0xE592427A0AEce92De3Edee1F18E0157C05861564',
    uniswapV3Quoter:  '0x61fFE014bA17989E743c5F6cB21bF9697530B21e',
    uniswapV3Factory: '0x1F98431c8aD98523631AE4a59f267346ea31F984',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270', // WMATIC
    wbtc:             '0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6',
  },
  // ── ZKsync Era (324) ───────────────────────────────────────
  324: {
    uniswapV3Router:  '0x99c56385dB8B93f67A212e6473437b93117E77C3',
    uniswapV3Quoter:  '0x8Cb537fc92E26d8EBBb760E632c95484b6Ea3e28',
    uniswapV3Factory: '0x8FdA5a7a8dCA67BBcDd10F02Fa0649A937215422',
    multicall3:       '0xF9cda624FBC7e059355ce98a31693d299FACd963',
    weth:             '0x5AEa5775959fBC2557Cc8789bC1bf90A239D9a91',
    wbtc:             null,
  },
  // ── Base Mainnet (8453) ─────────────────────────────────────
  8453: {
    uniswapV3Router:  '0x2626664c2603336E57B271c5C0b26F421741e481',
    uniswapV3Quoter:  '0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a',
    uniswapV3Factory: '0x33128a8fC17869897dcE68Ed026d694621f6FDfD',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0x4200000000000000000000000000000000000006',
    wbtc:             '0xcbB7C0000AB88B473b1f5aFd9ef808440eed33Bf', // cbBTC
  },
  // ── Arbitrum One (42161) ────────────────────────────────────
  42161: {
    uniswapV3Router:  '0xE592427A0AEce92De3Edee1F18E0157C05861564',
    uniswapV3Quoter:  '0x61fFE014bA17989E743c5F6cB21bF9697530B21e',
    uniswapV3Factory: '0x1F98431c8aD98523631AE4a59f267346ea31F984',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
    wbtc:             '0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f',
  },
  // ── Celo (42220) ────────────────────────────────────────────
  42220: {
    uniswapV3Router:  '0x5615CDAb10dc425a742d643d949a7F474C01abc4',
    uniswapV3Quoter:  '0x82825d0554fA07f7FC52Ab63c961F330fdEFa8E8',
    uniswapV3Factory: '0xAfE208a311B21f13EF87E33A90049fC17A7acDEc',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0x471EcE3750Da237f93B8E339c536989b8978a438', // WCELO
    wbtc:             null,
  },
  // ── Avalanche (43114) ───────────────────────────────────────
  43114: {
    uniswapV3Router:  '0xbb00FF08d01D300023C629E8fFfFcb65A5a578cE',
    uniswapV3Quoter:  '0xbe0F5544EC67e9B3b2D979aaA43f18Fd87E6257F',
    uniswapV3Factory: '0x740b1c1de25031C31FF4fC9A62f554A55cdC1baD',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7', // WAVAX
    wbtc:             '0x50b7545627a5162F82A992c33b87aDc75187B218',
  },
  // ── Blast (81457) ───────────────────────────────────────────
  81457: {
    uniswapV3Router:  '0x549FEB8c9bd4c12Ad2AB27022dA12492aC452B66',
    uniswapV3Quoter:  '0x6Cdcd65e03c1CEc3730AeeCd45bc140D57A25C77',
    uniswapV3Factory: '0x33128a8fC17869897dcE68Ed026d694621f6FDfD',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0x4300000000000000000000000000000000000004',
    wbtc:             null,
  },
  // ── Base Sepolia (84532) — testnet ──────────────────────────
  84532: {
    uniswapV3Router:  '0x94cC0AaC535CCDB3C01d6787D6413C739ae12bc4',
    uniswapV3Quoter:  '0xC5290058841028F1614F3A6F0F5816cAd0df5E27',
    uniswapV3Factory: '0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24',
    multicall3:       '0xcA11bde05977b3631167028862bE2a173976CA11',
    weth:             '0x4200000000000000000000000000000000000006',
    wbtc:             null,
  },
};
