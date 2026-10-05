import { Alert, Skeleton } from "@heroui/react";
import Link from "next/link";

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div role="status" className="rounded-2xl border border-dashed border-border p-8 text-center">
      <p className="font-medium">{title}</p>
      {hint ? <p className="mt-1 text-sm text-muted">{hint}</p> : null}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", detail, retry }: { title?: string; detail?: string; retry?: () => void }) {
  return (
    <Alert status="danger" role="alert">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>{title}</Alert.Title>
        {detail ? <Alert.Description>{detail}</Alert.Description> : null}
        <p className="mt-2 text-sm"><Link className="underline" href="/">Back to the overview</Link>{retry ? <> · <button className="underline" onClick={retry} type="button">Try again</button></> : null}</p>
      </Alert.Content>
    </Alert>
  );
}

export function LoadingState() {
  return (
    <div aria-busy="true" aria-label="Loading" className="space-y-4">
      <Skeleton className="h-24 rounded-2xl" />
      <div className="grid gap-4 sm:grid-cols-3"><Skeleton className="h-28 rounded-2xl" /><Skeleton className="h-28 rounded-2xl" /><Skeleton className="h-28 rounded-2xl" /></div>
      <Skeleton className="h-64 rounded-2xl" />
    </div>
  );
}
