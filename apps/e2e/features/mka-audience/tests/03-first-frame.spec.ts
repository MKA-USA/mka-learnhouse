import { test, expect } from '@playwright/test'
import type { Browser } from '@playwright/test'
import { SECTIONS, UNTARGETED, HIDDEN_FOR } from '../fixture'
import { PERSONAS } from '../personas'
import type { PersonaKey, SectionKey } from '../personas'
import { newPersonaContext, seeded, settle, stackAvailable } from '../helpers'

test.skip(!stackAvailable(), 'MKA e2e stack is not running (apps/e2e/mka/stack.sh up)')

/**
 * "No flash of hidden content": a rAF loop that starts at DOMContentLoaded samples the DOM on every animation frame
 * while the lesson hydrates and the viewer attributes load. Hidden sections must not be in the DOM in ANY frame
 * (checked against the lesson body, where the section content lives; the table of contents has its own spec). A
 * MutationObserver on the editor root additionally catches content that is inserted and removed between two frames.
 */
async function sampleLoad(browser: Browser, key: PersonaKey, hidden: SectionKey[]) {
  const hiddenBodies = hidden.map((k) => SECTIONS[k].body)
  const hiddenHeadings = hidden.map((k) => SECTIONS[k].heading)
  const ctx = await newPersonaContext(browser, key)
  const page = await ctx.newPage()
    await page.addInitScript(
      ([bodies, headings, untargeted]) => {
        const w = window as any
        w.__mka = { frames: 0, framesWithEditor: 0, firstEditorFrame: -1, leaks: [] as string[], sawUntargeted: false }
        const check = (where: string, text: string, list: string[]) => {
          for (const m of list) if (text.includes(m)) w.__mka.leaks.push(`${where}: ${m}`)
        }
        const start = () => {
          const t0 = performance.now()
          const loop = () => {
            const root = document.querySelector('.ProseMirror')
            const rootText = root?.textContent ?? ''
            w.__mka.frames++
            if (root) {
              w.__mka.framesWithEditor++
              if (w.__mka.firstEditorFrame < 0) w.__mka.firstEditorFrame = w.__mka.frames
              if (rootText.includes(untargeted)) w.__mka.sawUntargeted = true
            }
            check(`frame ${w.__mka.frames} editor`, rootText, [...bodies, ...headings])
            check(`frame ${w.__mka.frames} body`, document.body?.textContent ?? '', bodies)
            if (performance.now() - t0 < 12_000) requestAnimationFrame(loop)
          }
          requestAnimationFrame(loop)
          new MutationObserver((records) => {
            for (const r of records) {
              r.addedNodes.forEach((n) => {
                const text = n.textContent ?? ''
                check('mutation', text, bodies)
                if ((n as Element).closest?.('.ProseMirror')) check('mutation (editor)', text, headings)
              })
            }
          }).observe(document.documentElement, { childList: true, subtree: true })
        }
        document.addEventListener('DOMContentLoaded', start)
      },
      [hiddenBodies, hiddenHeadings, UNTARGETED.body] as const,
    )
    try {
      await page.goto(seeded().learnerUrl)
      await settle(page)
      await page.waitForTimeout(1500) // let the loop sample a few frames after settling
      return (await page.evaluate(() => (window as any).__mka)) as { frames: number; sawUntargeted: boolean; leaks: string[] }
    } finally {
      await ctx.close()
    }
  }

for (const p of PERSONAS.filter((x) => x.key !== 'author')) {
  test(`${p.label}: no hidden marker in the DOM on any animation frame while loading`, async ({ browser }) => {
    const r = await sampleLoad(browser, p.key, HIDDEN_FOR(p.visible))
    expect(r.frames, 'rAF loop did not run').toBeGreaterThan(5)
    expect(r.sawUntargeted, 'sampling never covered the rendered lesson').toBe(true)
    expect(r.leaks, `hidden content appeared in the DOM: ${JSON.stringify(r.leaks.slice(0, 5))}`).toEqual([])
  })
}

// Negative control: the admin legitimately sees every section, so the same detector must report leaks. Proves the
// sampler can see section content at all (otherwise the tests above would pass vacuously).
test('detector control: the admin view trips the sampler', async ({ browser }) => {
  const r = await sampleLoad(browser, 'admin', ['localTabligh', 'regionalQaids', 'national', 'hideNational', 'majlisAlbany'])
  expect(r.leaks.length).toBeGreaterThan(0)
})
