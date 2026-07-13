import { NextRequest, NextResponse } from 'next/server'

import {
  forwardToBackend,
  isAuthorized,
  notConfigured,
} from '@/lib/admin/approvalsBridge'

/** GET /api/admin/approvals — the pending-merchant review queue. */
export async function GET(req: NextRequest) {
  const missing = notConfigured()
  if (missing) return missing
  if (!(await isAuthorized(req))) {
    return NextResponse.json(
      { error: 'UNAUTHORIZED', message: 'Invalid or missing admin token.' },
      { status: 401 },
    )
  }
  return forwardToBackend('/admin/approvals')
}
