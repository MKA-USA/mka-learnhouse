// MKA fork — slash-menu items for audience sections (B1.1). Registered as a module side effect on the
// upstream `slashCommands` array, so no edit to the upstream slash config is needed.
import React from 'react'
import { Braces, Eye, Users } from 'lucide-react'
import { slashCommands } from '@components/Objects/Editor/Extensions/SlashCommands'
import type { SlashCommandItem } from '@components/Objects/Editor/Extensions/SlashCommands/types'
import { FIELD_FALLBACKS, FIELD_LABELS, VIEWER_FIELDS } from './fields'

let registered = false

export function registerMkaSlashItems(): void {
  if (registered) return
  registered = true
  const items: SlashCommandItem[] = [
    {
      id: 'mka-audience',
      title: 'Audience section',
      description: 'Show this only to certain officeholders',
      icon: <Eye className="size-5" />,
      category: 'interactive',
      keywords: ['audience', 'show only to', 'role', 'officeholder', 'visibility', 'who sees'],
      command: (editor) => {
        editor.chain().focus().setMkaAudience().run()
      },
    },
    ...VIEWER_FIELDS.map<SlashCommandItem>((field) => ({
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
  slashCommands.push(...items)
}
