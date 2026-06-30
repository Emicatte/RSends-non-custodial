import { redirect } from 'next/navigation'

// The API documentation now lives at the English-only, next-intl–excluded docs
// site under /docs (see app/docs/*). The previous single-page ApiDocs hub here
// described an outdated, partly-custodial surface and has been retired. The
// localized legal pages (privacy/terms/cookies/aml-kyc) remain under this route.
export default function LocalizedDocsRedirect() {
  redirect('/docs')
}
