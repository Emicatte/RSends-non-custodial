'use client'

/**
 * /onboarding/pending — the post-KYB waiting room. The profile is submitted
 * and the org sits at approval_status=pending_approval; the screen polls and
 * transitions on its own (see components/onboarding/ApprovalPendingScreen).
 */

import { OnboardingStepIndicator } from '@/components/onboarding/OnboardingStepIndicator'
import { ApprovalPendingScreen } from '@/components/onboarding/ApprovalPendingScreen'

export default function ApprovalPendingPage() {
  return (
    <div className="space-y-10">
      <OnboardingStepIndicator current="approval" />
      <ApprovalPendingScreen />
    </div>
  )
}
