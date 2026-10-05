// MKA fork: route-level skeleton, same chrome as dash/analytics/loading.tsx.
function SkeletonBlock({ className = '' }: { className?: string }) {
  return <div className={`bg-gray-200 rounded animate-pulse ${className}`} />
}

export default function Loading() {
  return (
    <div className="h-full w-full bg-[#f8f8f8] flex flex-col" role="status" aria-live="polite">
      <span className="sr-only">Loading compliance</span>
      <div className="ps-4 pe-4 sm:ps-10 sm:pe-10 tracking-tight bg-[#fcfbfc] z-10 nice-shadow flex-shrink-0 relative">
        <div className="pt-6 pb-4">
          <SkeletonBlock className="h-4 w-32" />
        </div>
        <div className="my-2 py-2 pb-5">
          <div className="flex flex-col space-y-3">
            <SkeletonBlock className="h-10 w-56" />
            <SkeletonBlock className="h-5 w-80 max-w-full" />
          </div>
        </div>
      </div>
      <div className="h-6 flex-shrink-0" />
      <div className="flex-1 overflow-hidden px-4 sm:px-10 pb-10 space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
          {Array.from({ length: 7 }).map((_, i) => (
            <SkeletonBlock key={i} className="h-[92px] rounded-xl" />
          ))}
        </div>
        <SkeletonBlock className="h-72 rounded-xl" />
        <SkeletonBlock className="h-[520px] rounded-xl" />
      </div>
    </div>
  )
}
