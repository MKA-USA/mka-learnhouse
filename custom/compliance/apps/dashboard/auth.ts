import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { env } from "@/lib/env";

/** Domain gate. Exported for tests: relies on Google's verified email, not on the `hd` hint alone. */
export function isAllowedAccount(profile: { email?: string | null; email_verified?: boolean | null } | undefined, domain = env.allowedDomain()): boolean {
  const email = profile?.email?.trim().toLowerCase();
  if (!email || profile?.email_verified !== true) return false;
  const at = email.lastIndexOf("@");
  return at > 0 && email.slice(at + 1) === domain;
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google({ authorization: { params: { hd: env.allowedDomain(), prompt: "select_account" } } })],
  session: { strategy: "jwt", maxAge: 60 * 60 * 8 },
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    signIn: ({ profile }) => isAllowedAccount(profile as { email?: string; email_verified?: boolean }),
    jwt: ({ token, profile }) => { if (profile?.email) token.email = profile.email.toLowerCase(); return token; },
    session: ({ session, token }) => { if (token.email && session.user) session.user.email = String(token.email); return session; },
  },
});
