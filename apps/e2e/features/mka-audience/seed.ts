/**
 * Idempotent seeding through the real APIs: persona users + attribute overrides, the fixture course/activity, and the
 * course-author relationship. Run from the MKA global setup; the result is written to <stateDir>/personas.json.
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { Api } from './api'
import { lessonDoc, V2_TAIL } from './fixture'
import { EMAIL_DOMAIN, PERSONA_PASSWORD, PERSONAS, emailFor } from './personas'
import type { PersonaKey } from './personas'
import { adminPassword, requireStack } from './stack'

export interface SeededPersona {
  key: PersonaKey
  label: string
  email: string
  password: string
  userId: number
  storageState: string
}

export interface Seeded {
  webUrl: string
  apiV1: string
  orgId: number
  orgSlug: string
  courseUuid: string
  courseId: number
  chapterId: number
  activityUuid: string
  activityId: number
  /** bare uuids as used in learner URLs */
  learnerUrl: string
  editorUrl: string
  personas: Record<PersonaKey, SeededPersona>
}

export const SEED_FILE = (stateDir: string) => `${stateDir}/personas.json`
export const AUTH_DIR = (stateDir: string) => `${stateDir}/auth`

const usernameOf = (local: string) => local.replace(/-/g, '_')

async function ensureUser(api: Api, adminToken: string, orgId: number, local: string, first: string, last: string): Promise<number> {
  const email = `${local}@${EMAIL_DOMAIN}`
  const r = await api.raw('POST', `/users/${orgId}`, adminToken, {
    email,
    username: usernameOf(local),
    password: PERSONA_PASSWORD,
    first_name: first,
    last_name: last,
    mka_profile: { majlis: 'Albany' },
  })
  if (r.status >= 200 && r.status < 300) return JSON.parse(r.text).id
  // Already exists (re-run): look it up.
  const found = await api.raw('GET', `/users/username/${usernameOf(local)}`, adminToken)
  if (found.status === 200) return JSON.parse(found.text).id
  throw new Error(`could not create or find ${email}: ${r.status} ${r.text.slice(0, 300)}`)
}

export async function seed(): Promise<Seeded> {
  const stack = requireStack()
  const api = new Api(stack)
  const adminEmail = stack.adminEmail
  const adminToken = await api.login(adminEmail, adminPassword(stack))
  const org = await api.json<{ id: number }>('GET', `/orgs/slug/${stack.orgSlug}`, null)

  // The bootstrapped admin has no MKA profile, and the non-dismissible "Complete your profile" gate would cover the page.
  await api.json('PUT', '/mka/profile/me', adminToken, { majlis: 'Albany' })

  const personas = {} as Record<PersonaKey, SeededPersona>
  const adminMe = await api.json<any>('GET', '/users/profile', adminToken).catch(() => null)
  personas.admin = {
    key: 'admin',
    label: 'Org admin',
    email: adminEmail,
    password: adminPassword(stack),
    userId: adminMe?.id ?? 1,
    storageState: `${AUTH_DIR(stack.stateDir)}/admin.json`,
  }

  for (const p of PERSONAS) {
    const userId = await ensureUser(api, adminToken, org.id, p.local, 'E2E', p.label.slice(0, 40))
    if (p.override) {
      await api.json('PUT', `/mka/attributes/users/${userId}/override?org_id=${org.id}`, adminToken, {
        override: p.override,
        reason: 'Audience e2e synthetic persona',
      })
    }
    personas[p.key] = {
      key: p.key,
      label: p.label,
      email: emailFor(p),
      password: PERSONA_PASSWORD,
      userId,
      storageState: `${AUTH_DIR(stack.stateDir)}/${p.key}.json`,
    }
  }

  // Fixture course: created by the admin, then the plain author account is made its ACTIVE CREATOR (the role
  // cannot create courses itself), so it is an author of the course but not an org admin/maintainer.
  const stamp = Date.now().toString(36)
  const fd = new FormData()
  fd.set('name', `Audience E2E ${stamp}`)
  fd.set('description', 'Seeded by the MKA audience e2e')
  fd.set('public', 'true')
  fd.set('about', 'Seeded by the MKA audience e2e')
  fd.set('learnings', '[]')
  fd.set('tags', '')
  const course = await api.json<any>('POST', `/courses/?org_id=${org.id}`, adminToken, undefined, fd)
  const chapter = await api.json<any>('POST', '/chapters/', adminToken, {
    name: 'Chapter 1',
    description: '',
    org_id: org.id,
    course_id: course.id,
  })
  const activity = await api.json<any>('POST', `/activities/?coursechapter_id=${chapter.id}&org_id=${org.id}`, adminToken, {
    name: 'Audience fixture lesson',
    activity_type: 'TYPE_DYNAMIC',
    activity_sub_type: 'SUBTYPE_DYNAMIC_PAGE',
    chapter_id: chapter.id,
    published: true,
  })
  // Two saves so the version history has something to preview (v2 adds one trailing paragraph).
  await api.json('PUT', `/activities/${activity.activity_uuid}`, adminToken, { content: lessonDoc() })
  await api.json('PUT', `/activities/${activity.activity_uuid}`, adminToken, { content: lessonDoc({ withV2Tail: true }) })

  await api.json('POST', `/courses/${course.course_uuid}/bulk-add-contributors`, adminToken, [usernameOf(PERSONAS.find((x) => x.key === 'author')!.local)])
  await api.json(
    'PUT',
    `/courses/${course.course_uuid}/contributors/${personas.author.userId}?authorship=CREATOR&authorship_status=ACTIVE`,
    adminToken,
  )

  const bareCourse = String(course.course_uuid).replace('course_', '')
  const bareActivity = String(activity.activity_uuid).replace('activity_', '')
  const seeded: Seeded = {
    webUrl: stack.webUrl,
    apiV1: stack.apiV1,
    orgId: org.id,
    orgSlug: stack.orgSlug,
    courseUuid: course.course_uuid,
    courseId: course.id,
    chapterId: chapter.id,
    activityUuid: activity.activity_uuid,
    activityId: activity.id,
    learnerUrl: `${stack.webUrl}/course/${bareCourse}/activity/${bareActivity}`,
    editorUrl: `${stack.webUrl}/course/${bareCourse}/activity/${bareActivity}/edit`,
    personas,
  }
  mkdirSync(AUTH_DIR(stack.stateDir), { recursive: true })
  writeFileSync(SEED_FILE(stack.stateDir), JSON.stringify(seeded, null, 2))
  void V2_TAIL
  return seeded
}
