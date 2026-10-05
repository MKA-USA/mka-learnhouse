// MKA fork — viewer-field constants shared by the node and its view.
export const VIEWER_FIELDS = ['majlis', 'region', 'department', 'role_title', 'level'] as const
export type ViewerFieldKey = (typeof VIEWER_FIELDS)[number]

export const FIELD_FALLBACKS: Record<ViewerFieldKey, string> = {
  majlis: 'your Majlis',
  region: 'your region',
  department: 'your department',
  role_title: 'your role',
  level: 'your level',
}

export const FIELD_LABELS: Record<ViewerFieldKey, string> = {
  majlis: 'Majlis',
  region: 'Region',
  department: 'Department',
  role_title: 'Role',
  level: 'Level',
}

export const isField = (v: unknown): v is ViewerFieldKey => (VIEWER_FIELDS as readonly string[]).includes(v as string)

/** Words an author might type while looking for "show this to some people only". Title stays "Audience section". */
export const AUDIENCE_KEYWORDS = [
  'audience', 'visible', 'visibility', 'show', 'show only', 'show only to', 'show to', 'hide', 'hide from', 'only',
  'who', 'see', 'restrict', 'restricted', 'target', 'targeted', 'targeting', 'who can see', 'who sees', 'role', 'roles', 'officeholder',
  'officeholders', 'office holder', 'level', 'department', 'region', 'majlis', 'conditional', 'condition', 'permission',
  'private', 'limit', 'section',
]
