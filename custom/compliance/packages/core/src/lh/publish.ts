import type { LhApi } from "./api";

export interface PublishTarget { courseUuid: string; name: string; activities: { key: string; uuid: string; assignmentUuid?: string }[] }
export interface PublishItem { level: "activity" | "assignment" | "course"; key: string; uuid: string }

/**
 * The ONLY code path that sets published=true. Called solely by the explicit `publish --execute` command.
 * Bypasses the draft-only guards in LhApi on purpose (uses the raw client). Order: activities, assignments, course last.
 */
export function publishPlan(t: PublishTarget): PublishItem[] {
  return [
    ...t.activities.map((a): PublishItem => ({ level: "activity", key: a.key, uuid: a.uuid })),
    ...t.activities.filter((a) => a.assignmentUuid).map((a): PublishItem => ({ level: "assignment", key: a.key, uuid: a.assignmentUuid! })),
    { level: "course", key: t.name, uuid: t.courseUuid },
  ];
}
export async function executePublish(api: LhApi, items: PublishItem[], log: (s: string) => void = () => {}): Promise<number> {
  for (const i of items) {
    const path = i.level === "course" ? `/courses/${i.uuid}` : i.level === "activity" ? `/activities/${i.uuid}` : `/assignments/${i.uuid}`;
    await api.client.put(path, { published: true });
    log(`published ${i.level} ${i.key}`);
  }
  return items.length;
}
