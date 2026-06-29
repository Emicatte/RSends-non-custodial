/**
 * app/pay/_components/walletTheme.ts — RainbowKit theme for the /pay subtree.
 *
 * Light surface + terracotta accent so the Connect button and modal match the
 * brand card. Applied via a nested RainbowKitProvider in app/pay/page.tsx; the
 * shared WalletStackFull (darkTheme) and every other route are untouched.
 *
 * Built from brand tokens (no duplicated hex). fontStack stays 'system' — that
 * only styles modal chrome; page numerics remain DM Mono.
 */
import { lightTheme, type Theme } from '@rainbow-me/rainbowkit'
import { C } from '@/app/designTokens'

export const rsendsWalletTheme: Theme = lightTheme({
  accentColor: C.purple, // #C8512C terracotta — primary CTA
  accentColorForeground: C.bg, // #FAFAFA paper — text/icons on the accent
  borderRadius: 'medium',
  overlayBlur: 'small',
  fontStack: 'system',
})
