'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'
import type { OrgRole } from '@/hooks/useOrganizations'

export interface MembershipItem {
  id: string
  user_id: string
  user_email: string
  user_display_name: string | null
  role: OrgRole
  joined_at: string
}

export interface MembershipListPayload {
  memberships: MembershipItem[]
  max_allowed: number
}

export interface InviteItem {
  id: string
  email: string
  role: OrgRole
  status: string
  created_at: string
  expires_at: string
}

export interface InvitesListPayload {
  invites: InviteItem[]
}

export interface InviteMemberInput {
  email: string
  role: OrgRole
}

export function useOrgMembers(orgId: string | null) {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [members, setMembers] = useState<MembershipItem[]>([])
  const [maxAllowed, setMaxAllowed] = useState<number>(10)
  const [invites, setInvites] = useState<InviteItem[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    tokenRef.current = (session as { access_token?: string } | null)
      ?.access_token
  }, [session])

  useEffect(() => {
    const onRefresh = (e: Event) => {
      const t = (e as CustomEvent<{ access_token?: string }>).detail
        ?.access_token
      if (t) tokenRef.current = t
    }
    window.addEventListener('rsends:token-refreshed', onRefresh)
    return () => window.removeEventListener('rsends:token-refreshed', onRefresh)
  }, [])

  const reload = useCallback(async () => {
    if (status !== 'authenticated' || !accessToken || !orgId) {
      setMembers([])
      setInvites([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const [membersData, invitesData] = await Promise.all([
        apiCall<MembershipListPayload>(
          `/api/v1/organizations/${orgId}/members`,
          tokenRef.current,
        ),
        apiCall<InvitesListPayload>(
          `/api/v1/organizations/${orgId}/invites`,
          tokenRef.current,
        ).catch(() => ({ invites: [] } as InvitesListPayload)),
      ])
      setMembers(membersData.memberships)
      setMaxAllowed(membersData.max_allowed)
      setInvites(invitesData.invites)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      console.error('[useOrgMembers] reload', e)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken, orgId])

  useEffect(() => {
    void reload()
  }, [reload])

  const inviteMember = useCallback(
    async (input: InviteMemberInput): Promise<InviteItem> => {
      if (!orgId) throw new Error('no_active_org')
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        const result = await apiCall<InviteItem>(
          `/api/v1/organizations/${orgId}/invites`,
          token,
          {
            method: 'POST',
            body: JSON.stringify(input),
          },
        )
        await reload()
        return result
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [orgId, reload],
  )

  const changeRole = useCallback(
    async (targetUserId: string, role: OrgRole): Promise<void> => {
      if (!orgId) throw new Error('no_active_org')
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<MembershipItem>(
          `/api/v1/organizations/${orgId}/members/${targetUserId}/role`,
          token,
          {
            method: 'PATCH',
            body: JSON.stringify({ role }),
          },
        )
        await reload()
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [orgId, reload],
  )

  const removeMember = useCallback(
    async (targetUserId: string): Promise<void> => {
      if (!orgId) throw new Error('no_active_org')
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<void>(
          `/api/v1/organizations/${orgId}/members/${targetUserId}`,
          token,
          { method: 'DELETE' },
        )
        await reload()
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [orgId, reload],
  )

  const revokeInvite = useCallback(
    async (inviteId: string): Promise<void> => {
      if (!orgId) throw new Error('no_active_org')
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<void>(
          `/api/v1/organizations/${orgId}/invites/${inviteId}`,
          token,
          { method: 'DELETE' },
        )
        await reload()
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [orgId, reload],
  )

  return {
    members,
    maxAllowed,
    invites,
    loading,
    saving,
    error,
    reload,
    inviteMember,
    changeRole,
    removeMember,
    revokeInvite,
    clearError: () => setError(null),
  }
}
