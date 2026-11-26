// Layout audit probe: finds decorative accents (left border / inset box-shadow / ::before bars) that sit too close to
// the content they decorate, text that overflows its box, and horizontal page scroll. Runs inside the page.
import type { Page } from '@playwright/test';

export interface Finding { kind: string; selector: string; detail: string; text?: string }

export async function auditLayout(page: Page, minGap = 8): Promise<Finding[]> {
  return page.evaluate((MIN) => {
    const out: any[] = [];
    const sel = (e: Element) => {
      let s = e.tagName.toLowerCase();
      if ((e as HTMLElement).id) s += '#' + (e as HTMLElement).id;
      const c = (e.getAttribute('class') || '').split(/\s+/).filter(Boolean).slice(0, 3).join('.');
      return c ? s + '.' + c : s;
    };
    const visible = (e: Element) => { if (e.closest('.sr-only')) return false; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
    // left-most content edge inside `el`: text nodes and child elements that paint something
    const contentLeft = (el: Element) => {
      let min = Infinity;
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let n: Node | null;
      while ((n = walker.nextNode())) {
        if (!(n.textContent || '').trim()) continue;
        const pe = (n as Text).parentElement!; if (!visible(pe)) continue;
        const rg = document.createRange(); rg.selectNodeContents(n);
        for (const r of Array.from(rg.getClientRects())) if (r.width > 0 && r.height > 0) min = Math.min(min, r.left);
      }
      for (const c of Array.from(el.querySelectorAll('button,input,select,svg,img,canvas,.badge-c,.badge-sev,.chip,.tbl'))) {
        if (!visible(c)) continue; min = Math.min(min, c.getBoundingClientRect().left);
      }
      return min;
    };
    const all = Array.from(document.querySelectorAll('body *')).filter(visible);
    for (const e of all) {
      const cs = getComputedStyle(e); const r = e.getBoundingClientRect();
      // inside a scrolled-away or clipped container: ignore
      let accent = 0;
      const bl = parseFloat(cs.borderLeftWidth) || 0;
      if (bl >= 2 && cs.borderLeftStyle !== 'none') accent = Math.max(accent, bl);
      const m = cs.boxShadow.match(/inset\s+(-?\d+(?:\.\d+)?)px\s+0px\s+0px\s+0px|(?:rgba?\([^)]*\)|color\([^)]*\)|#[0-9a-f]+)\s+(\d+(?:\.\d+)?)px\s+0px\s+0px\s+0px\s+inset/i);
      if (m) accent = Math.max(accent, parseFloat(m[1] || m[2]) || 0);
      if (accent < 2) continue;
      if (e.tagName === 'TD' || e.tagName === 'TH') {
        // table cell accent: content is the cell's own children
      }
      const cl = contentLeft(e);
      if (!isFinite(cl)) continue;
      const gap = cl - (r.left + accent);
      if (gap < MIN - 0.5) out.push({ kind: 'accent-too-close', selector: sel(e), detail: 'accent ' + accent + 'px, gap to content ' + gap.toFixed(1) + 'px (min ' + MIN + ')', text: (e.textContent || '').trim().slice(0, 40) });
    }
    // ::before/::after absolute bars hugging content are covered by the border/shadow check above; check text overflow
    for (const e of all) {
      const cs = getComputedStyle(e);
      if (!e.childNodes.length) continue;
      const hasText = Array.from(e.childNodes).some((n) => n.nodeType === 3 && (n.textContent || '').trim());
      if (!hasText) continue;
      const ox = cs.overflowX;
      if ((ox === 'hidden' || ox === 'clip') && e.clientWidth > 2 && e.scrollWidth > e.clientWidth + 1 && cs.textOverflow !== 'ellipsis') {
        out.push({ kind: 'text-clipped', selector: sel(e), detail: 'scrollWidth ' + e.scrollWidth + ' > clientWidth ' + e.clientWidth, text: (e.textContent || '').trim().slice(0, 40) });
      }
    }
    // status labels, chips, buttons and tabs must show their full text (long names in lists may ellipsize, labels may not)
    for (const e of all) {
      if (!e.matches('.badge-c,.badge-sev,.chip,.fchip,.sc-pill,.btn,.sc-tab,.tab-c,.rsec-status')) continue;
      const cs = getComputedStyle(e);
      if (e.clientWidth > 2 && e.scrollWidth > e.clientWidth + 1 && (cs.textOverflow === 'ellipsis' || cs.overflowX === 'hidden')) {
        out.push({ kind: 'label-truncated', selector: sel(e), detail: 'scrollWidth ' + e.scrollWidth + ' > clientWidth ' + e.clientWidth, text: (e.textContent || '').trim().slice(0, 40) });
      }
    }
    const de = document.documentElement;
    if (de.scrollWidth > de.clientWidth + 1) out.push({ kind: 'page-h-scroll', selector: 'html', detail: de.scrollWidth + ' > ' + de.clientWidth });
    return out;
  }, minGap);
}

// Collapse a long list of '[WxH] where: finding' lines into one line per distinct finding, with how many window sizes hit it.
export function summarise(lines: string[]): string[] {
  const m = new Map<string, { n: number; first: string }>();
  for (const l of lines) { const k = l.replace(/^\[[^\]]*\]\s*/, ''); const e = m.get(k); if (e) e.n++; else m.set(k, { n: 1, first: (l.match(/^\[[^\]]*\]/) || [''])[0] }); }
  return Array.from(m.entries()).map(([k, v]) => `${v.first} x${v.n} ${k}`);
}
