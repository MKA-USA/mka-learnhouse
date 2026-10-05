import Link from "next/link";
export default function NotFound() {
  return <main className="mx-auto max-w-xl px-4 py-16 text-center"><h1 className="text-xl font-semibold">Nothing to show here</h1><p className="mt-2 text-sm text-muted">This page doesn&apos;t exist, or it isn&apos;t part of what you can see.</p><p className="mt-4"><Link className="underline" href="/">Back to the overview</Link></p></main>;
}
