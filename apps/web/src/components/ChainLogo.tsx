'use client'

interface ChainLogoProps {
  chainId: number
  size?: number
  className?: string
}

export function ChainLogo({ chainId, size = 20, className = '' }: ChainLogoProps) {
const logo = CHAIN_LOGOS[Number(chainId)]
  if (!logo) {
    const name = CHAIN_META[Number(chainId)]?.name || '?'
    const color = CHAIN_META[Number(chainId)]?.color || '#666'
    return (
      <div
        className={className}
        style={{
          width: size, height: size, borderRadius: '50%',
          background: color, display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontSize: size * 0.45,
          fontWeight: 700, color: '#fff',
        }}
      >
        {name[0]}
      </div>
    )
  }
  return (
    <svg
      width={size} height={size} viewBox={logo.viewBox}
      className={className}
      style={{ borderRadius: '50%' }}
    >
      {logo.content}
    </svg>
  )
}

export const CHAIN_META: Record<number, { name: string; color: string; shortName: string }> = {
  1:     { name: 'Ethereum',  color: '#627EEA', shortName: 'ETH' },
  10:    { name: 'Optimism',  color: '#FF0420', shortName: 'OP' },
  56:    { name: 'BNB Chain', color: '#F3BA2F', shortName: 'BNB' },
  137:   { name: 'Polygon',   color: '#8247E5', shortName: 'POL' },
  324:   { name: 'ZKsync',    color: '#8C8DFC', shortName: 'ZK' },
  8453:  { name: 'Base',      color: '#0052FF', shortName: 'Base' },
  42161: { name: 'Arbitrum',  color: '#12AAFF', shortName: 'ARB' },
  42220: { name: 'Celo',      color: '#FCFF52', shortName: 'CELO' },
  43114: { name: 'Avalanche', color: '#E84142', shortName: 'AVAX' },
  81457: { name: 'Blast',     color: '#FCFC03', shortName: 'BLAST' },
  84532: { name: 'Sepolia',   color: '#0052FF', shortName: 'Sep' },
}

const CHAIN_LOGOS: Record<number, { viewBox: string; content: JSX.Element }> = {

  // -- Ethereum --
  1: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#627EEA" />
        <path d="M16.498 4v8.87l7.497 3.35z" fill="#fff" fillOpacity=".6" />
        <path d="M16.498 4L9 16.22l7.498-3.35z" fill="#fff" />
        <path d="M16.498 21.968v6.027L24 17.616z" fill="#fff" fillOpacity=".6" />
        <path d="M16.498 27.995v-6.028L9 17.616z" fill="#fff" />
        <path d="M16.498 20.573l7.497-4.353-7.497-3.348z" fill="#fff" fillOpacity=".2" />
        <path d="M9 16.22l7.498 4.353v-7.701z" fill="#fff" fillOpacity=".6" />
      </>
    ),
  },

  // -- Optimism --
  10: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#FF0420" />
        <path d="M10.5 19.94c-1.69 0-2.97-.46-3.84-1.37-.86-.92-1.29-2.2-1.29-3.84 0-2.05.52-3.77 1.57-5.16 1.06-1.4 2.55-2.1 4.47-2.1 1.07 0 1.96.22 2.67.67.72.44 1.25 1.06 1.6 1.85.35.79.53 1.7.53 2.73 0 2.06-.53 3.78-1.58 5.16-1.04 1.37-2.5 2.06-4.13 2.06zm.31-2.44c.75 0 1.38-.44 1.88-1.31.51-.88.76-2.06.76-3.55 0-.99-.17-1.76-.5-2.31-.33-.56-.82-.84-1.45-.84-.76 0-1.39.44-1.9 1.31-.5.87-.75 2.04-.75 3.51 0 1.01.17 1.79.51 2.35.34.56.83.84 1.45.84z" fill="#fff" />
        <path d="M19.46 19.73V7.68h3.45c1.62 0 2.74.32 3.37.95.63.63.94 1.48.94 2.55 0 1.18-.37 2.17-1.12 2.97-.74.79-1.75 1.19-3.04 1.19h-1.17v4.39h-2.43zm2.43-6.73h.71c.65 0 1.15-.2 1.5-.6.36-.4.53-.93.53-1.58 0-.52-.14-.93-.42-1.22-.28-.3-.73-.44-1.36-.44h-0.96v3.84z" fill="#fff" />
      </>
    ),
  },

  // -- BNB Chain --
  56: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#F3BA2F" />
        <path d="M16 6l2.91 2.91-5.82 5.82L16 17.64l5.82-5.82L16 6zm-7.09 7.09L16 20.18l7.09-7.09 2.91 2.91L16 26l-10-10 2.91-2.91z" fill="#fff" />
      </>
    ),
  },

  // -- Polygon --
  137: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#8247E5" />
        <path d="M21.092 13.68c-.37-.215-.845-.215-1.264 0l-2.966 1.72-2.012 1.12-2.917 1.72c-.37.214-.845.214-1.264 0l-2.323-1.34c-.37-.215-.62-.645-.62-1.075v-2.63c0-.43.202-.86.62-1.075l2.274-1.29c.37-.215.845-.215 1.264 0l2.274 1.29c.37.215.62.645.62 1.075v1.72l2.012-1.17v-1.72c0-.43-.202-.86-.62-1.075l-4.237-2.46c-.37-.215-.845-.215-1.264 0l-4.335 2.51c-.37.215-.62.645-.62 1.075v4.87c0 .43.202.86.62 1.075l4.286 2.46c.37.215.845.215 1.264 0l2.917-1.67 2.012-1.17 2.917-1.67c.37-.215.845-.215 1.264 0l2.274 1.29c.37.215.62.645.62 1.075v2.63c0 .43-.202.86-.62 1.075l-2.225 1.34c-.37.215-.845.215-1.264 0l-2.274-1.29c-.37-.215-.62-.645-.62-1.075v-1.72l-2.012 1.17v1.72c0 .43.202.86.62 1.075l4.286 2.46c.37.215.845.215 1.264 0l4.286-2.46c.37-.215.62-.645.62-1.075v-4.92c0-.43-.202-.86-.62-1.075l-4.335-2.46z" fill="#fff" />
      </>
    ),
  },

  // -- ZKsync --
  324: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#8C8DFC" />
        <path d="M22 10l-6 4.5V19l6-4.5V10zm-12 3l6 4.5V22l-6-4.5V13z" fill="#fff" />
        <path d="M10 13l6-4.5V13l-6 4.5V13zm12 6l-6 4.5V19l6-4.5v4.5z" fill="#fff" fillOpacity=".6" />
      </>
    ),
  },

  // -- Base --
  8453: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#0052FF" />
        <path d="M16 27c6.075 0 11-4.925 11-11S22.075 5 16 5C10.352 5 5.621 9.208 5.043 14.667h13.29v2.666H5.043C5.62 22.792 10.352 27 16 27z" fill="#fff" />
      </>
    ),
  },

  // -- Base Sepolia --
  84532: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#0052FF" />
        <path d="M16 27c6.075 0 11-4.925 11-11S22.075 5 16 5C10.352 5 5.621 9.208 5.043 14.667h13.29v2.666H5.043C5.62 22.792 10.352 27 16 27z" fill="#fff" />
        <text x="16" y="30" textAnchor="middle" fontSize="4" fill="#fff" opacity=".5">TEST</text>
      </>
    ),
  },

  // -- Arbitrum --
  42161: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#12AAFF" />
        <path d="M16.62 12.88l3.44 5.48-1.94 1.16-3.44-5.48 1.94-1.16zm-5.86 9.38l1.94-1.16 1.76 2.8-1.94 1.16-1.76-2.8z" fill="#fff" />
        <path d="M21.24 7.74L16 4 10.76 7.74l5.24 3.14 5.24-3.14z" fill="#fff" fillOpacity=".6" />
        <path d="M10.76 7.74v8.22L16 19.1l5.24-3.14V7.74L16 10.88l-5.24-3.14z" fill="#fff" fillOpacity=".3" />
        <path d="M18.12 18.36l-1.94 1.16 1.76 2.8 1.94-1.16-1.76-2.8z" fill="#fff" />
      </>
    ),
  },

  // -- Celo --
  42220: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#35D07F" />
        <path d="M23.8 8.2H8.2v15.6h15.6V8.2zM16 22c-3.3 0-6-2.7-6-6 0-1.9.9-3.6 2.3-4.7l1.2 1.5C12.6 13.6 12 14.7 12 16c0 2.2 1.8 4 4 4 1.3 0 2.4-.6 3.2-1.5l1.5 1.2C19.6 21.1 17.9 22 16 22z" fill="#fff" />
        <path d="M20 16c0-2.2-1.8-4-4-4-.7 0-1.3.2-1.9.5l1.2 1.5c.2-.1.5-.1.7-.1 1.1 0 2 .9 2 2 0 .2 0 .5-.1.7l1.5 1.2c.4-.6.6-1.2.6-1.8z" fill="#fff" />
      </>
    ),
  },

  // -- Avalanche --
  43114: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#E84142" />
        <path d="M20.28 21.5h3.17c.44 0 .66-.01.78-.22.12-.2.01-.44-.22-.82l-7.78-13.82c-.23-.39-.46-.58-.73-.58s-.5.19-.73.58l-2.02 3.58 3.95 7.02 3.58 4.26z" fill="#fff" />
        <path d="M8.56 21.5h4.56l3.38-6-2.27-4.02-5.89 9.61c-.23.38-.34.62-.22.82.12.21.34.22.78.22l-.34-.63z" fill="#fff" fillOpacity=".6" />
      </>
    ),
  },

  // -- Blast --
  81457: {
    viewBox: '0 0 32 32',
    content: (
      <>
        <circle cx="16" cy="16" r="16" fill="#FCFC03" />
        <path d="M8 10h16l-2 4H10l-2-4zm2 6h12l-2 4H12l-2-4z" fill="#000" />
        <path d="M14 22h4l2-4h-8l2 4z" fill="#000" />
      </>
    ),
  },
}

export default ChainLogo
