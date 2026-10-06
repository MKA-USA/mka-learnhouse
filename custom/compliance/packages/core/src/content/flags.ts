export interface ContentFlag { code: string; severity: "warn" | "info"; detail: string }

const APPROVED_HOSTS = ["alislam.org"];
/** Operational links (resources, calendars, forms) are not citations of Islamic content. */
const OPERATIONAL_HOSTS = ["mkausa.org", "docs.google.com", "calendar.google.com", "forms.gle", "drive.google.com", "ahmadiyya-usa.my.site.com", "sites.google.com", "slides.google.com", "sheets.google.com"];
const hostIs = (h: string, list: string[]) => list.some((x) => h === x || h.endsWith(`.${x}`));
const OUTSIDE_SOURCE_RE = /\b(sahih\s+(?:al-)?bukhari|bukhari|sahih\s+muslim|tirmidhi|abu\s+dawu?d|ibn\s+majah|nasa'?i|musnad|ibn\s+kathir|tafsir\s+(?:al-)?(?:tabari|jalalayn)|wikipedia|britannica)\b/i;

/** Flags content that needs human review under the approved-sources rule. Never blocks. */
export function scanContent(input: { text: string; links: string[]; imagesDropped: number }): ContentFlag[] {
  const flags: ContentFlag[] = [];
  const seen = new Set<string>();
  for (const l of input.links) {
    if (l.startsWith("mailto:")) continue;
    let host = ""; try { host = new URL(l).hostname.toLowerCase(); } catch { continue; }
    const key = host; if (seen.has(key)) continue; seen.add(key);
    if (hostIs(host, APPROVED_HOSTS)) continue;
    if (hostIs(host, OPERATIONAL_HOSTS)) flags.push({ code: "operational-link", severity: "info", detail: `link to ${host} (operational; verify it is still shared)` });
    else flags.push({ code: "non-approved-source-link", severity: "warn", detail: `link to ${host} is outside alislam.org` });
  }
  const m = OUTSIDE_SOURCE_RE.exec(input.text);
  if (m) flags.push({ code: "outside-source-citation", severity: "warn", detail: `text mentions "${m[0]}" (not an approved source); review` });
  if (input.imagesDropped) flags.push({ code: "image-dropped", severity: "warn", detail: `${input.imagesDropped} image(s) dropped; confirm none depict the Holy Prophet (sa) or companions` });
  return flags;
}
