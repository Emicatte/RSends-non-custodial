import { NextRequest, NextResponse } from 'next/server'

import {
  forwardToBackend,
  isAuthorized,
  notConfigured,
} from '@/lib/admin/approvalsBridge'

/**
 * POST /api/admin/approvals/{orgId} — apply an approval decision.
 * Body: {"action": "approve"} or {"action": "decline", "reason": "..."}.
 */
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ orgId: string }> },
) {
  const missing = notConfigured()
  if (missing) return missing
  if (!(await isAuthorized(req))) {
    return NextResponse.json(
      { error: 'UNAUTHORIZED', message: 'Invalid or missing admin token.' },
      { status: 401 },
    )
  }

  const { orgId } = await params
  if (!/^[0-9a-fA-F-]{36}$/.test(orgId)) {
    return NextResponse.json({ error: 'INVALID_ORG_ID' }, { status: 400 })
  }

  const body = (await req.json().catch(() => ({}))) as {
    action?: string
    reason?: string
  }

  if (body.action === 'approve') {
    return forwardToBackend(`/admin/approvals/${orgId}/approve`, { method: 'POST' })
  }
  if (body.action === 'decline') {
    const reason = (body.reason ?? '').trim()
    if (!reason || reason.length > 2000) {
      return NextResponse.json({ error: 'INVALID_REASON' }, { status: 400 })
    }
    return forwardToBackend(`/admin/approvals/${orgId}/decline`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    })
  }
  return NextResponse.json({ error: 'INVALID_ACTION' }, { status: 400 })
}
