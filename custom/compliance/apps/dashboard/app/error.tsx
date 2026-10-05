"use client";
import { ErrorState } from "@/components/StateViews";
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return <main className="mx-auto max-w-3xl px-4 py-10"><ErrorState title="We couldn't load the dashboard" detail="The data may be refreshing. Try again in a minute." retry={reset} /></main>;
}
