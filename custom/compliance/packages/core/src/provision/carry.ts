import type { PMDoc } from "../content/pm";
import { LhHttpError } from "../lh/errors";
import type { ActivitySpec, CourseSpec } from "../templates/types";
import type { MapRow } from "./types";

export type SeedSource = "previous-cycle" | "csv";

const hasContent = (d: PMDoc | null | undefined): d is PMDoc => !!d && Array.isArray(d.content) && d.content.some((n) => n.type !== "paragraph" || (n.content?.length ?? 0) > 0);

/** Pure: initial content for an author-owned page is last cycle's page when it exists and is not empty, else the spec's own (CSV-derived) content. */
export function chooseSeed(csvDoc: PMDoc, prevDoc: PMDoc | null | undefined): { doc: PMDoc; source: SeedSource } {
  return hasContent(prevDoc) ? { doc: prevDoc, source: "previous-cycle" } : { doc: csvDoc, source: "csv" };
}

/**
 * Replace the doc of every author-owned page that apply is about to create (or hand over once) with the previous cycle's
 * version of the same activity (via the previous cycle's course_map row + `readDoc`). Pages already author-owned in
 * this cycle are left alone: apply skips them, so their spec content is irrelevant.
 */
export async function carryForward(spec: CourseSpec, o: { row: MapRow | null; prev: MapRow | null; readDoc: (activityUuid: string) => Promise<PMDoc | null> }):
  Promise<{ spec: CourseSpec; sources: Record<string, SeedSource> }> {
  const sources: Record<string, SeedSource> = {};
  const chapters = await Promise.all(spec.chapters.map(async (ch) => ({
    ...ch,
    activities: await Promise.all(ch.activities.map(async (a): Promise<ActivitySpec> => {
      if (a.kind !== "page" || (a.owner ?? "generated") !== "author") return a;
      if (o.row?.structure.activities[a.key]?.owner === "author") return a;
      // Only a previous page an author owned carries forward: pre-ownership (v1) records were generated pages with a different meaning.
      const prevRec = o.prev?.structure.activities[a.key];
      const prevUuid = prevRec?.owner === "author" ? prevRec.uuid : undefined;
      const prevDoc = prevUuid ? await o.readDoc(prevUuid) : null;
      const pick = chooseSeed(a.doc, prevDoc);
      sources[a.key] = pick.source;
      return { ...a, doc: pick.doc };
    })),
  })));
  return { spec: { ...spec, chapters }, sources };
}

/** Read a page's ProseMirror doc. null only when the activity is gone (404); any other failure propagates so a run never silently seeds from the CSV. */
export async function readPageDoc(api: { getActivity(uuid: string): Promise<{ content?: unknown }> }, uuid: string): Promise<PMDoc | null> {
  try { return ((await api.getActivity(uuid)).content as PMDoc | undefined) ?? null; }
  catch (e) { if (e instanceof LhHttpError && e.status === 404) return null; throw e; }
}
