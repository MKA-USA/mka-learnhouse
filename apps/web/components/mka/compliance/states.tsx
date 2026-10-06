'use client'
import React from 'react'
import { CircleSlash, FileQuestion, ShieldAlert, ServerCrash, Users2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { errorStatus } from '@services/mka/compliance'

export function StateCard({
  icon,
  title,
  children,
  action,
  className,
  role,
}: {
  icon: React.ReactNode
  title: string
  children?: React.ReactNode
  action?: React.ReactNode
  className?: string
  role?: 'status' | 'alert'
}) {
  return (
    <div className={cn('flex min-h-64 flex-col items-center justify-center py-10 text-center', className)} role={role}>
      <div className="max-w-md rounded-2xl border border-gray-100 bg-white p-8 nice-shadow">
        <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-gray-100 text-gray-500">{icon}</div>
        <h2 className="mb-1.5 text-base font-bold text-gray-900">{title}</h2>
        {children ? <p className="text-sm leading-relaxed text-gray-500">{children}</p> : null}
        {action ? <div className="mt-4">{action}</div> : null}
      </div>
    </div>
  )
}

export const NoCycleState = () => (
  <StateCard icon={<FileQuestion className="size-5" aria-hidden="true" />} title="No cycle imported yet" role="status">
    Compliance numbers appear here once a cycle and its expected roster have been imported. Check back soon.
  </StateCard>
)

export const NoExpectedState = ({ label }: { label?: string }) => (
  <StateCard icon={<Users2 className="size-5" aria-hidden="true" />} title="0 expected learners" role="status">
    {label ? `Cycle ${label} has no expected officeholders yet.` : 'This cycle has no expected officeholders yet.'} Import the
    roster to start tracking.
  </StateCard>
)

export const NoAccessState = () => (
  <StateCard icon={<ShieldAlert className="size-5" aria-hidden="true" />} title="You don't have access to compliance data" role="status">
    Compliance views are available to course creators and organization admins. If you think you should see this, ask your
    organization admin.
  </StateCard>
)

/** 403 -> no access; 404 -> generic not-found (never confirms another course exists); else retryable error. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const status = errorStatus(error)
  if (status === 403) return <NoAccessState />
  if (status === 404) {
    return (
      <StateCard icon={<CircleSlash className="size-5" aria-hidden="true" />} title="Nothing to show here" role="status">
        We couldn&apos;t find compliance data for this page.
      </StateCard>
    )
  }
  return (
    <StateCard
      icon={<ServerCrash className="size-5" aria-hidden="true" />}
      title="Couldn't load compliance data"
      role="alert"
      action={
        onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            Try again
          </button>
        ) : undefined
      }
    >
      Something went wrong on our side. Your data is unchanged.
    </StateCard>
  )
}

const Bar = ({ className }: { className?: string }) => <div className={cn('rounded bg-gray-200/80', className)} />

/** Skeletons match final heights so nothing jumps when data lands. */
export function SummaryCardsSkeleton() {
  return (
    <div className="animate-pulse" aria-hidden="true">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="h-[92px] rounded-xl bg-white p-4 nice-shadow">
            <Bar className="mb-3 h-3 w-16" />
            <Bar className="h-6 w-12" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function PanelSkeleton({ height = 'h-80' }: { height?: string }) {
  return (
    <div className={cn('animate-pulse rounded-xl bg-white p-5 nice-shadow', height)} aria-hidden="true">
      <Bar className="mb-5 h-4 w-40" />
      <div className="space-y-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Bar key={i} className="h-8 w-full" />
        ))}
      </div>
    </div>
  )
}

export function PageLoading({ label = 'Loading compliance data' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="space-y-6">
      <span className="sr-only">{label}</span>
      <SummaryCardsSkeleton />
      <PanelSkeleton height="h-72" />
      <PanelSkeleton height="h-[520px]" />
    </div>
  )
}
