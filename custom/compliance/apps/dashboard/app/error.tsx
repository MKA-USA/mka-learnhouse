"use client";
import { ErrorState } from "@/components/StateViews";
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="mx-auto max-w-3xl px-4 py-10"><ErrorState title="We couldn't load the dashboard" detail={process.env.NODE_ENV === "development" ? error.message : "The data may be refreshing. Try again in a minute."} retry={reset} /></main>;
}
