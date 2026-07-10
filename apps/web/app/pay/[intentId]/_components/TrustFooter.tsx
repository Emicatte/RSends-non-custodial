'use client'

/**
 * TrustFooter — exactly two trust elements, both factually accurate: the
 * non-custodial line and the immutable-contract line with a View contract
 * link to the router address on the explorer (central chain config).
 * Nothing beyond these two.
 */

import { useTranslations } from 'next-intl'
import { C } from '@/app/designTokens'
import { explorerAddressUrl } from '@/lib/web3/explorer'

export function TrustFooter({
  chainId,
  router,
}: {
  chainId: number
  router: string
}) {
  const t = useTranslations('pay')
  const line = {
    margin: 0,
    fontFamily: C.D,
    fontSize: 12.5,
    lineHeight: 1.5,
    color: C.sub,
  } as const

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        borderTop: `1px solid ${C.border}`,
        paddingTop: 14,
      }}
    >
      <p style={line}>{t('trust.nonCustodial')}</p>
      <p style={line}>
        {t('trust.contract')}{' '}
        <a
          href={explorerAddressUrl(chainId, router)}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: C.purple, textDecoration: 'none', fontFamily: C.M, fontSize: 12 }}
        >
          {t('trust.viewContract')}
        </a>
      </p>
    </div>
  )
}
