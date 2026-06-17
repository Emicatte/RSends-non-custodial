// lib/features.tsx
//
// Single source of truth for the public "feature" pages that back the
// homepage "Why sign in" cards. Holds only structure — routing slugs,
// ordering, cross-links and icons. All translatable copy lives in i18n
// under the `features.*` namespace (messages/<locale>.json), matching the
// existing pattern used elsewhere in the app.

import type { ReactElement } from 'react'

export type FeatureKey =
  | 'savedRoutes'
  | 'crossDeviceHistory'
  | 'encryptedContacts'
  | 'smartNotifications'

export type FeatureCardKey = 'routes' | 'history' | 'contacts' | 'notifications'

export interface Feature {
  /** i18n namespace key under `features.*` and the FeaturePage prop value */
  key: FeatureKey
  /** public route slug under /[locale]/<slug> */
  slug: string
  /** key used by the homepage WhySignInSection feature list */
  cardKey: FeatureCardKey
  /** inline SVG glyph (matches the homepage card icons) */
  Icon: () => ReactElement
  /** true → "How it works" shows numbered steps; false → unnumbered capability cards */
  sequential: boolean
  /** key into the FeatureVisuals VISUALS map (1:1 with `key`) */
  visual: FeatureKey
}

export const FEATURES: readonly Feature[] = [
  { key: 'savedRoutes',        slug: 'saved-routes',         cardKey: 'routes',        Icon: RouteIcon,     sequential: true,  visual: 'savedRoutes' },
  { key: 'crossDeviceHistory', slug: 'cross-device-history', cardKey: 'history',       Icon: HistoryIcon,   sequential: false, visual: 'crossDeviceHistory' },
  { key: 'encryptedContacts',  slug: 'encrypted-contacts',   cardKey: 'contacts',      Icon: ContactsIcon,  sequential: false, visual: 'encryptedContacts' },
  { key: 'smartNotifications', slug: 'smart-notifications',  cardKey: 'notifications', Icon: BellIcon,      sequential: false, visual: 'smartNotifications' },
] as const

export function getFeature(key: FeatureKey): Feature {
  const f = FEATURES.find((x) => x.key === key)
  if (!f) throw new Error(`Unknown feature key: ${key}`)
  return f
}

/** Slug for a homepage card key (used to make the cards navigate). */
export function slugForCardKey(cardKey: FeatureCardKey): string {
  const f = FEATURES.find((x) => x.cardKey === cardKey)
  return f ? f.slug : ''
}

/** The other three features, for the "More reasons to sign in" strip. */
export function otherFeatures(key: FeatureKey): Feature[] {
  return FEATURES.filter((x) => x.key !== key)
}

// ── Icons (1:1 with the homepage WhySignInSection glyphs) ──────────────────

function RouteIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="6" cy="19" r="3" />
      <circle cx="18" cy="5" r="3" />
      <path d="M6.7 17.3L17.3 6.7" />
    </svg>
  )
}

function HistoryIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
      <path d="M12 7v5l3 2" />
    </svg>
  )
}

function ContactsIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

function BellIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  )
}
