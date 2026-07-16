import { redirect } from 'next/navigation'

// The legacy custodial consumer landing that lived here is retired; the
// marketing site is the [locale] tree. Full removal of the custodial
// components it rendered is tracked in CLAUDE.md (dormant custodial residue).
export default function RootIndex() {
  redirect('/en')
}
