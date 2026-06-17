'use client'

import { useSession } from 'next-auth/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiCall, waitForToken } from '@/lib/auth-client'

export type OrgRole = 'admin' | 'operator' | 'viewer'

export interface OrganizationListItem {
  id: string
  name: string
  slug: string
  owner_user_id: string
  is_personal: boolean
  plan: string
  role: OrgRole
  member_count: number
  created_at: string
}

export interface OrganizationListPayload {
  organizations: OrganizationListItem[]
  active_org_id: string | null
}

export interface CreateOrgInput {
  name: string
}

export interface UpdateOrgInput {
  name?: string
}

export function useOrganizations() {
  const { data: session, status } = useSession()
  const accessToken = (session as { access_token?: string } | null)?.access_token
  const tokenRef = useRef<string | undefined>(accessToken)

  const [organizations, setOrganizations] = useState<OrganizationListItem[]>([])
  const [activeOrgId, setActiveOrgId] = useState<string | null>(null)
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
    if (status !== 'authenticated' || !accessToken) {
      setOrganizations([])
      setActiveOrgId(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await apiCall<OrganizationListPayload>(
        '/api/v1/organizations',
        tokenRef.current,
      )
      setOrganizations(data.organizations)
      setActiveOrgId(data.active_org_id)
    } catch (e) {
      const code = e instanceof Error ? e.message : 'unknown'
      setError(code)
      console.error('[useOrganizations] reload', e)
    } finally {
      setLoading(false)
    }
  }, [status, accessToken])

  useEffect(() => {
    void reload()
  }, [reload])

  const createOrganization = useCallback(
    async (input: CreateOrgInput): Promise<OrganizationListItem> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        const result = await apiCall<OrganizationListItem>(
          '/api/v1/organizations',
          token,
          {
            method: 'POST',
            body: JSON.stringify({ name: input.name }),
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
    [reload],
  )

  const switchActive = useCallback(
    async (orgId: string): Promise<void> => {
      setSaving(true)
      setError(null)
      const prev = activeOrgId
      setActiveOrgId(orgId)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<{ active_org_id: string }>(
          '/api/v1/organizations/switch',
          token,
          {
            method: 'POST',
            body: JSON.stringify({ org_id: orgId }),
          },
        )
        // Prompt 11: notify listeners (useUserApiKeys, useUserWallets, etc.)
        // that org-scoped resources must be reloaded now that the active org
        // has changed.
        if (typeof window !== 'undefined') {
          window.dispatchEvent(
            new CustomEvent('rsends:active-org-changed', {
              detail: { orgId },
            }),
          )
        }
      } catch (e) {
        setActiveOrgId(prev)
        const code = e instanceof Error ? e.message : 'unknown'
        setError(code)
        throw e
      } finally {
        setSaving(false)
      }
    },
    [activeOrgId],
  )

  const updateOrganization = useCallback(
    async (orgId: string, patch: UpdateOrgInput): Promise<void> => {
      setSaving(true)
      setError(null)
      try {
        const token = await waitForToken(tokenRef)
        await apiCall<OrganizationListItem>(
          `/api/v1/organizations/${orgId}`,
          token,
          {
            method: 'PATCH',
            body: JSON.stringify(patch),
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
    [reload],
  )

  return {
    organizations,
    activeOrgId,
    loading,
    saving,
    error,
    isAuthed: status === 'authenticated',
    reload,
    createOrganization,
    switchActive,
    updateOrganization,
    clearError: () => setError(null),
  }
}
