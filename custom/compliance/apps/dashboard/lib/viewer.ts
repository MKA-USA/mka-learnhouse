import { cookies } from "next/headers";
import { auth } from "@/auth";
import { env } from "@/lib/env";
import { personaByKey } from "@/lib/personas";

export interface Viewer { email: string; name: string | null; devPersona?: string }

/** The signed-in viewer, or null. Fixture mode (non-production only) uses the persona cookie instead of Google. */
export async function getViewer(): Promise<Viewer | null> {
  if (env.fixtureMode()) {
    const key = (await cookies()).get("dev_persona")?.value;
    const p = personaByKey(key) ?? personaByKey("motamid")!;
    return { email: p.email, name: p.label, devPersona: p.key };
  }
  const s = await auth();
  const email = s?.user?.email?.trim().toLowerCase();
  return email ? { email, name: s?.user?.name ?? null } : null;
}
