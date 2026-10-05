'use client'
// MKA fork — hidden-for-this-viewer placeholder and read-only badge. Lazy: only authors / can_view_all viewers render them.
import React from 'react'
import { DEFAULT_RULE } from '../audience/types'
import type { Rule } from '../audience/types'
import { HiddenPlaceholder, ReadOnlyBadge } from './AudienceHeader'

export default function SectionNotice({ kind, label, rule }: { kind: 'placeholder' | 'badge'; label: string; rule: Rule | null }) {
  return kind === 'placeholder' ? (
    <HiddenPlaceholder label={label} className="my-1" />
  ) : (
    <ReadOnlyBadge rule={rule ?? DEFAULT_RULE} label={label} className="mb-1" />
  )
}
