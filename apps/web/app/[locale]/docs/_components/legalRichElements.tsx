import type { ReactNode } from 'react'
import { Link } from '@/i18n/navigation'

export const richElements = {
  strong: (chunks: ReactNode) => <strong>{chunks}</strong>,
  em: (chunks: ReactNode) => <em>{chunks}</em>,
  code: (chunks: ReactNode) => <code>{chunks}</code>,
  br: () => <br />,
  privacyMail: (chunks: ReactNode) => <a href="mailto:privacy@rsends.io">{chunks}</a>,
  legalMail: (chunks: ReactNode) => <a href="mailto:legal@rsends.io">{chunks}</a>,
  complianceMail: (chunks: ReactNode) => <a href="mailto:compliance@rsends.io">{chunks}</a>,
  linkPrivacy: (chunks: ReactNode) => <Link href="/docs/privacy">{chunks}</Link>,
  linkTerms: (chunks: ReactNode) => <Link href="/docs/terms">{chunks}</Link>,
  linkCookies: (chunks: ReactNode) => <Link href="/docs/cookies">{chunks}</Link>,
  linkAmlKyc: (chunks: ReactNode) => <Link href="/docs/aml-kyc">{chunks}</Link>,
  linkPricing: (chunks: ReactNode) => <Link href="/pricing">{chunks}</Link>,
  chrome: (chunks: ReactNode) => (
    <a href="https://support.google.com/chrome/answer/95647" target="_blank" rel="noopener noreferrer">{chunks}</a>
  ),
  firefox: (chunks: ReactNode) => (
    <a href="https://support.mozilla.org/en-US/kb/enhanced-tracking-protection-firefox-desktop" target="_blank" rel="noopener noreferrer">{chunks}</a>
  ),
  safari: (chunks: ReactNode) => (
    <a href="https://support.apple.com/en-us/guide/safari/sfri11471/mac" target="_blank" rel="noopener noreferrer">{chunks}</a>
  ),
  edge: (chunks: ReactNode) => (
    <a href="https://support.microsoft.com/en-us/microsoft-edge" target="_blank" rel="noopener noreferrer">{chunks}</a>
  ),
}
