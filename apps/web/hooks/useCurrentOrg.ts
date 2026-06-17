'use client'

import { useMemo } from 'react'
import {
  useOrganizations,
  type OrganizationListItem,
  type OrgRole,
} from '@/hooks/useOrganizations'

export interface CurrentOrgState {
  activeOrg: OrganizationListItem | null
  role: OrgRole | null
  loading: boolean
  isAuthed: boolean
}

export function useCurrentOrg(): CurrentOrgState {
  const { organizations, activeOrgId, loading, isAuthed } = useOrganizations()

  return useMemo(() => {
    const activeOrg =
      organizations.find((o) => o.id === activeOrgId) ?? null
    return {
      activeOrg,
      role: activeOrg?.role ?? null,
      loading,
      isAuthed,
    }
  }, [organizations, activeOrgId, loading, isAuthed])
}
