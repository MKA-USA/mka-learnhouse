// Enumerate what a user could act on. Deterministic: the model later picks among these ids, never selectors.
import type { Page } from 'playwright-core'

export type El = {
  id: string // e1..eN
  kind: 'button' | 'link' | 'text' | 'editor' | 'select' | 'checkbox' | 'tab' | 'option' | 'other'
  name: string
  state: string // e.g. "expanded", "checked", "disabled"
  css: string // stable css path used for deterministic replay
  desc: string // one-line description shown to the model
}
export type Observation = { url: string; title: string; text: string; els: El[]; dialogOpen: boolean; focus: string | null }

/** Runs inside the page. Keep self-contained (serialised by Playwright). */
function collect(max: number) {
  const SEL = 'a[href],button,input,select,textarea,summary,[role=button],[role=menuitem],[role=menuitemradio],[role=option],[role=tab],[role=checkbox],[role=radio],[role=switch],[role=combobox],[role=link],[contenteditable=true],[contenteditable=""],[tabindex]:not([tabindex="-1"])'
  const cssPath = (el: Element): string => {
    const parts: string[] = []
    let n: Element | null = el
    while (n && n.nodeType === 1 && n !== document.documentElement) {
      const tag = n.tagName.toLowerCase()
      const parent: Element | null = n.parentElement
      if (!parent) break
      const idx = Array.from(parent.children).indexOf(n) + 1
      parts.unshift(`${tag}:nth-child(${idx})`)
      n = parent
    }
    return 'html > ' + parts.join(' > ')
  }
  const visible = (el: Element) => {
    const r = el.getBoundingClientRect()
    if (r.width < 2 || r.height < 2) return false
    const st = getComputedStyle(el)
    if (st.visibility === 'hidden' || st.display === 'none' || st.pointerEvents === 'none') return false
    if (el.closest('[aria-hidden=true],[inert]')) return false
    if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false
    const cx = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1)
    const cy = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1)
    const top = document.elementFromPoint(cx, cy)
    return !!top && (el === top || el.contains(top) || top.contains(el))
  }
  const nameOf = (el: HTMLElement) => {
    const lab = el.getAttribute('aria-label') || el.getAttribute('title') || (el as HTMLInputElement).placeholder
    const t = (lab || el.innerText || (el as HTMLInputElement).value || '').replace(/\s+/g, ' ').trim()
    return t.slice(0, 70)
  }
  const out: Array<{ kind: string; name: string; state: string; css: string }> = []
  const seen = new Set<string>()
  const dialog = document.querySelector('[role=dialog],[role=alertdialog],[data-state=open][role=menu],[role=listbox],[role=menu]')
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(SEL))) {
    if (el.closest('nextjs-portal,[data-nextjs-toast],[data-nextjs-dev-tools-button],[class*=tsqd]')) continue
    if (!visible(el)) continue
    const tag = el.tagName.toLowerCase()
    const role = el.getAttribute('role') || ''
    const editable = el.isContentEditable && el.getAttribute('contenteditable') !== 'false'
    let kind = 'other'
    if (editable && (el.classList.contains('ProseMirror') || el.closest('.ProseMirror') === el)) kind = 'editor'
    else if (editable) continue // nested contenteditable inside the editor: the editor root is the one actionable element
    else if (tag === 'a' || role === 'link') kind = 'link'
    else if (tag === 'select') kind = 'select'
    else if (tag === 'textarea' || (tag === 'input' && !['checkbox', 'radio', 'button', 'submit'].includes((el as HTMLInputElement).type))) kind = 'text'
    else if (role === 'checkbox' || role === 'radio' || role === 'switch' || (tag === 'input' && ['checkbox', 'radio'].includes((el as HTMLInputElement).type))) kind = 'checkbox'
    else if (role === 'tab') kind = 'tab'
    else if (role === 'option' || role.startsWith('menuitem')) kind = 'option'
    else if (tag === 'button' || role === 'button' || tag === 'summary') kind = 'button'
    // skip elements inside the editor body that are not controls (ProseMirror inner nodes)
    if (kind === 'other' && el.closest('.ProseMirror')) continue
    if (/devtools/i.test(el.getAttribute('aria-label') || '')) continue
    const name = kind === 'editor' ? 'rich-text editor (document body)' : nameOf(el)
    const st: string[] = []
    if ((el as HTMLButtonElement).disabled || el.getAttribute('aria-disabled') === 'true') st.push('disabled')
    const ex = el.getAttribute('aria-expanded'); if (ex) st.push(ex === 'true' ? 'expanded' : 'collapsed')
    const ch = el.getAttribute('aria-checked') ?? ((el as HTMLInputElement).checked ? 'true' : null); if (ch) st.push(ch === 'true' ? 'checked' : 'unchecked')
    const pr = el.getAttribute('aria-pressed') ?? el.getAttribute('aria-selected') ?? el.getAttribute('data-state'); if (pr) st.push(String(pr))
    if (kind === 'text' && (el as HTMLInputElement).value) st.push('has value')
    const key = kind + '|' + name + '|' + st.join(',') + '|' + Math.round(el.getBoundingClientRect().top / 8)
    if (seen.has(key)) continue
    seen.add(key)
    out.push({ kind, name, state: st.join(', '), css: cssPath(el) })
    if (out.length >= max) break
  }
  const a = document.activeElement as HTMLElement | null
  const focus = a && (a.isContentEditable || a.tagName === 'INPUT' || a.tagName === 'TEXTAREA') ? (a.isContentEditable ? 'the rich-text editor' : `text field "${(a.getAttribute('aria-label') || (a as HTMLInputElement).placeholder || a.tagName).slice(0, 40)}"`) : null
  return { els: out, dialogOpen: !!dialog, focus, text: (document.body.innerText || '').replace(/\n{2,}/g, '\n').trim() }
}

export async function observe(page: Page, max = 45): Promise<Observation> {
  const r = await page.evaluate(collect, max)
  const els: El[] = r.els.map((e, i) => {
    const kind = e.kind as El['kind']
    const id = `e${i + 1}`
    const desc = `${kind}${e.name ? ` "${e.name}"` : ''}${e.state ? ` [${e.state}]` : ''}`
    return { id, kind, name: e.name, state: e.state, css: e.css, desc }
  })
  return { url: new URL(page.url()).pathname + new URL(page.url()).search, title: await page.title(), text: r.text, els, dialogOpen: r.dialogOpen, focus: r.focus }
}
