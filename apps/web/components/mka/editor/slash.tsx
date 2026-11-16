// MKA fork — slash-menu items for audience sections (B1.1). Registered as a module side effect on the
// upstream `slashCommands` array, so no edit to the upstream slash config is needed.
import React from 'react'
import { Braces, Eye, Users } from 'lucide-react'
import { slashCommands } from '@components/Objects/Editor/Extensions/SlashCommands'
import type { SlashCommandItem } from '@components/Objects/Editor/Extensions/SlashCommands/types'
import { AUDIENCE_KEYWORDS, FIELD_FALLBACKS, FIELD_LABELS, VIEWER_FIELDS } from './fields'

let registered = false

export function registerMkaSlashItems(): void {
  if (registered) return
  registered = true
  type MkaSlashItem = Omit<SlashCommandItem, 'titleKey' | 'descriptionKey'>
  const items: MkaSlashItem[] = [
    {
      id: 'mka-audience',
      title: 'Audience section',
      description: 'Show this part only to certain officeholders',
      icon: <Eye className="size-5" />,
      category: 'interactive',
      keywords: AUDIENCE_KEYWORDS,
      command: (editor) => {
        editor.chain().focus().setMkaAudience().run()
      },
    },
    ...VIEWER_FIELDS.map<MkaSlashItem>((field) => ({
      id: `mka-field-${field}`,
      title: `Viewer's ${FIELD_LABELS[field]}`,
      description: `Fills in the viewer's ${FIELD_LABELS[field].toLowerCase()}, or "${FIELD_FALLBACKS[field]}"`,
      icon: <Braces className="size-5" />,
      category: 'interactive',
      keywords: ['viewer', 'my', field.replace('_', ' '), 'field', 'placeholder'],
      command: (editor) => {
        editor
          .chain()
          .focus()
          .insertContent({ type: 'mkaViewerField', attrs: { field, fallback: FIELD_FALLBACKS[field] } })
          .run()
      },
    })),
    {
      id: 'mka-counterparts',
      title: 'My counterparts',
      description: "A card with the viewer's national, regional and local contacts",
      icon: <Users className="size-5" />,
      category: 'interactive',
      keywords: ['counterparts', 'contacts', 'mailbox', 'my team'],
      command: (editor) => {
        editor.chain().focus().insertContent({ type: 'mkaCounterparts' }).run()
      },
    },
  ]
  // Upstream renders `t(item.titleKey)`; with no catalogue entry i18next returns the key itself, so the
  // English title/description double as keys (no '.' or ':' in any of them).
  slashCommands.push(...items.map((item) => ({ ...item, titleKey: item.title, descriptionKey: item.description })))
}
