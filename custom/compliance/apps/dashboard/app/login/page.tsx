import { signIn } from "@/auth";
import { env } from "@/lib/env";

export default async function Login({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <main className="mx-auto max-w-sm px-4 py-20">
      <h1 className="text-2xl font-semibold">MKA compliance dashboard</h1>
      <p className="mt-2 text-sm text-muted">Sign in with your @{env.allowedDomain()} Google account.</p>
      {error ? <p role="alert" className="mt-4 rounded-lg bg-danger-soft p-3 text-sm text-danger">That account can&apos;t sign in. Use your @{env.allowedDomain()} address.</p> : null}
      <form className="mt-6" action={async () => { "use server"; await signIn("google", { redirectTo: "/" }); }}>
        <button type="submit" className="w-full rounded-xl bg-accent px-4 py-2.5 font-medium text-accent-foreground">Continue with Google</button>
      </form>
    </main>
  );
}
