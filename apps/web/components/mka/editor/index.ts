// MKA fork — entry point hooked into the upstream editors (W1/W2/W3, contract §4).
import type { AnyExtension } from '@tiptap/core'
import { waitForMkaAudienceEnabled } from '@services/mka/flags'
import { MkaAudience } from './AudienceNode'
import { MkaViewerField } from './ViewerFieldNode'
import { MkaCounterparts } from './CounterpartsNode'
import { minimalMkaNodes } from './minimalNodes'

export type MkaEditorOptions = {
  /** True for the authoring editor only. The EditorContext provider remains the source of truth in node views. */
  editable: boolean
  activity?: any
  /** Optional hints from the hook site; otherwise derived from the activity / route (see useAudienceScope). */
  courseUuid?: string | null
  orgId?: number | null
}

let slashWaiting = false

function registerSlash(): void {
  // Lazy: keeps the slash config (and its image imports) out of read-only viewer bundles and out of tests.
  import('./slash').then((m) => m.registerMkaSlashItems()).catch(() => undefined)
}

/**
 * Extensions for every TipTap instance that loads activity content. Registering the nodes is mandatory
 * everywhere: with an unknown node, TipTap renders the whole lesson blank. This function therefore never
 * throws and always returns the nodes; at worst they are schema-only (no views, no plugins).
 */
export function mkaEditorExtensions(opts: MkaEditorOptions): AnyExtension[] {
  const { editable, activity, courseUuid = null, orgId = null } = opts
  try {
    // Runtime flag: may flip on after hydration (runtime-config.js), so wait for it instead of checking once.
    if (editable && !slashWaiting) {
      slashWaiting = true // one pending wait at a time, however many editors are created
      waitForMkaAudienceEnabled(
        () => {
          slashWaiting = false
          registerSlash()
        },
        { onGiveUp: () => (slashWaiting = false) },
      )
    }
  } catch {
    /* authoring entry points are optional */
  }
  try {
    return [
      MkaAudience.configure({ editable, activity, courseUuid, orgId }),
      MkaViewerField.configure({ activity, courseUuid, orgId }),
      MkaCounterparts.configure({ activity, courseUuid, orgId }),
    ]
  } catch (err) {
    if (process.env.NODE_ENV !== 'production') console.error('[mka-audience] falling back to schema-only nodes', err)
    return minimalMkaNodes()
  }
}

export { MkaAudience, MkaViewerField, MkaCounterparts }
