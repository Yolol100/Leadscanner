import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { chromium, devices } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const OUT = path.resolve('scan-results');
const runLighthouse = String(process.env.RUN_LIGHTHOUSE || 'false').toLowerCase() === 'true';
const singleTarget = (process.env.TARGET_URL || '').trim();
const safe = (value) => value.replace(/^https?:\/\//, '').replace(/[^a-z0-9.-]+/gi, '_').replace(/_+/g, '_').slice(0, 100);

await fs.rm(OUT, { recursive: true, force: true });
await fs.mkdir(OUT, { recursive: true });

const fileLines = singleTarget ? [] : (await fs.readFile('sites.txt', 'utf8')).split(/\r?\n/);
const urls = [...new Set((singleTarget ? [singleTarget] : fileLines)
  .map((x) => x.trim())
  .filter((x) => x && !x.startsWith('#'))
  .map((x) => /^https?:\/\//i.test(x) ? x : `https://${x}`))];

if (!urls.length) throw new Error('Geen websites gevonden. Zet URLs in sites.txt of gebruik TARGET_URL.');

const browser = await chromium.launch({ headless: true });
const allResults = [];

const profiles = [
  { name: 'desktop', options: { viewport: { width: 1440, height: 900 } } },
  { name: 'mobile', options: { ...devices['iPhone 13'] } },
];

const interestingLink = /(contact|offerte|aanvraag|afspraak|boek|booking|dienst|service|winkelwagen|cart|checkout)/i;
const placeholder = /\b(lorem ipsum|dummy text|placeholder|coming soon|under construction)\b/i;
const genericButton = /^(button|knop|click here|klik hier|read more|lees meer)$/i;

function addFinding(bucket, finding) {
  const key = `${finding.type}|${finding.url}|${finding.detail}`;
  if (!bucket._keys.has(key)) {
    bucket._keys.add(key);
    bucket.findings.push(finding);
  }
}

async function inspectPage(page, target, profileName, bucket) {
  const pageUrl = page.url();
  const title = await page.title().catch(() => '');
  const state = await page.evaluate(({ placeholderSource, genericButtonSource }) => {
    const visible = (el) => {
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
    };
    const text = (document.body?.innerText || '').replace(/\s+/g, ' ').trim();
    const placeholderRe = new RegExp(placeholderSource, 'i');
    const genericButtonRe = new RegExp(genericButtonSource, 'i');
    const brokenImages = [...document.images].filter((img) => img.complete && img.naturalWidth === 0 && visible(img)).slice(0, 10).map((img) => img.currentSrc || img.src);
    const genericButtons = [...document.querySelectorAll('button, a')].filter(visible).map((el) => (el.innerText || el.getAttribute('aria-label') || '').trim()).filter((t) => genericButtonRe.test(t)).slice(0, 10);
    const forms = [...document.forms].map((form) => ({
      action: form.action,
      method: (form.method || 'get').toUpperCase(),
      fields: [...form.querySelectorAll('input, select, textarea')].length,
    }));
    const overflow = document.documentElement.scrollWidth > window.innerWidth + 5;
    const links = [...document.querySelectorAll('a[href]')].filter(visible).map((a) => ({ href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim() })).slice(0, 300);
    return {
      textSample: text.slice(0, 5000),
      hasPlaceholder: placeholderRe.test(text),
      brokenImages,
      genericButtons,
      forms,
      overflow,
      links,
    };
  }, { placeholderSource: placeholder.source, genericButtonSource: genericButton.source });

  if (state.overflow && profileName === 'mobile') addFinding(bucket, { severity: 4, type: 'mobile_overflow', url: pageUrl, detail: 'Pagina is breder dan het mobiele scherm; horizontaal scrollen is nodig.' });
  if (state.brokenImages.length) addFinding(bucket, { severity: 3, type: 'broken_images', url: pageUrl, detail: `${state.brokenImages.length} zichtbare afbeelding(en) laden niet.` });
  if (state.hasPlaceholder) addFinding(bucket, { severity: 4, type: 'placeholder_content', url: pageUrl, detail: 'Zichtbare placeholder-/dummytekst aangetroffen.' });
  if (state.genericButtons.length) addFinding(bucket, { severity: 3, type: 'generic_cta', url: pageUrl, detail: `Generieke knoptekst: ${state.genericButtons.join(', ')}` });

  try {
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    for (const v of axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').slice(0, 5)) {
      addFinding(bucket, { severity: v.impact === 'critical' ? 4 : 3, type: 'accessibility', url: pageUrl, detail: `${v.impact}: ${v.help} (${v.nodes.length} element(en))` });
    }
  } catch (e) {
    addFinding(bucket, { severity: 1, type: 'axe_scan_error', url: pageUrl, detail: String(e.message || e).slice(0, 300) });
  }

  const maxSeverity = Math.max(0, ...bucket.findings.filter((f) => f.url === pageUrl).map((f) => f.severity));
  if (maxSeverity >= 3) {
    const shot = path.join(OUT, safe(target), `${profileName}-${safe(new URL(pageUrl).pathname || 'home')}.png`);
    await fs.mkdir(path.dirname(shot), { recursive: true });
    await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
  }

  return { url: pageUrl, title, forms: state.forms, links: state.links };
}

async function scanProfile(target, profile) {
  const context = await browser.newContext({
    ...profile.options,
    ignoreHTTPSErrors: false,
    userAgent: profile.options.userAgent || undefined,
  });
  const page = await context.newPage();
  const bucket = { profile: profile.name, findings: [], _keys: new Set(), pages: [] };

  page.on('console', (msg) => {
    if (msg.type() === 'error') addFinding(bucket, { severity: 2, type: 'console_error', url: page.url() || target, detail: msg.text().slice(0, 400) });
  });
  page.on('pageerror', (err) => addFinding(bucket, { severity: 3, type: 'javascript_error', url: page.url() || target, detail: String(err.message || err).slice(0, 400) }));
  page.on('response', (res) => {
    if (res.status() >= 400) {
      const resource = res.request().resourceType();
      const severity = resource === 'document' ? 5 : (['script', 'stylesheet', 'image'].includes(resource) ? 3 : 1);
      addFinding(bucket, { severity, type: 'http_error', url: page.url() || target, detail: `${res.status()} ${resource}: ${res.url()}` });
    }
  });

  try {
    const response = await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 30000 });
    if (!response) addFinding(bucket, { severity: 4, type: 'navigation_error', url: target, detail: 'Geen HTTP-response ontvangen voor de hoofdpagina.' });
    else if (response.status() >= 400) addFinding(bucket, { severity: 5, type: 'core_page_error', url: target, detail: `Hoofdpagina geeft HTTP ${response.status()}.` });
    await page.waitForTimeout(1200);
    const home = await inspectPage(page, target, profile.name, bucket);
    bucket.pages.push(home.url);

    let origin;
    try { origin = new URL(page.url()).origin; } catch { origin = new URL(target).origin; }
    const candidates = [...new Set(home.links
      .filter((l) => interestingLink.test(`${l.text} ${l.href}`))
      .map((l) => l.href.split('#')[0])
      .filter((href) => { try { return new URL(href).origin === origin; } catch { return false; } }))].slice(0, 2);

    for (const href of candidates) {
      try {
        const response2 = await page.goto(href, { waitUntil: 'domcontentloaded', timeout: 25000 });
        if (response2 && response2.status() >= 400) addFinding(bucket, { severity: 5, type: 'core_page_error', url: href, detail: `Belangrijke pagina geeft HTTP ${response2.status()}.` });
        await page.waitForTimeout(700);
        const inspected = await inspectPage(page, target, profile.name, bucket);
        bucket.pages.push(inspected.url);
      } catch (e) {
        addFinding(bucket, { severity: 4, type: 'core_page_unreachable', url: href, detail: `Belangrijke pagina kon niet worden geopend: ${String(e.message || e).slice(0, 250)}` });
      }
    }
  } catch (e) {
    addFinding(bucket, { severity: 4, type: 'site_unreachable', url: target, detail: `Website kon niet worden geopend: ${String(e.message || e).slice(0, 350)}` });
  }

  delete bucket._keys;
  await context.close();
  return bucket;
}

async function maybeRunLighthouse(target, siteResult) {
  const maxSeverity = Math.max(0, ...siteResult.profiles.flatMap((p) => p.findings.map((f) => f.severity)));
  if (!runLighthouse || maxSeverity < 3) return null;
  const dir = path.join(OUT, safe(target));
  await fs.mkdir(dir, { recursive: true });
  const output = path.join(dir, 'lighthouse.json');
  try {
    execFileSync('npx', ['lighthouse', target, '--quiet', '--output=json', `--output-path=${output}`, '--only-categories=performance,accessibility,best-practices,seo', '--chrome-flags=--headless --no-sandbox --disable-gpu'], { stdio: 'pipe', timeout: 90000 });
    const report = JSON.parse(await fs.readFile(output, 'utf8'));
    return Object.fromEntries(Object.entries(report.categories || {}).map(([k, v]) => [k, Math.round((v.score || 0) * 100)]));
  } catch (e) {
    return { error: String(e.message || e).slice(0, 400) };
  }
}

for (const target of urls) {
  const siteResult = { target, scannedAt: new Date().toISOString(), profiles: [] };
  for (const profile of profiles) siteResult.profiles.push(await scanProfile(target, profile));
  siteResult.lighthouse = await maybeRunLighthouse(target, siteResult);
  const findings = siteResult.profiles.flatMap((p) => p.findings.map((f) => ({ ...f, profile: p.profile })));
  siteResult.topFindings = findings.sort((a, b) => b.severity - a.severity).slice(0, 3);
  siteResult.candidate = siteResult.topFindings.some((f) => f.severity >= 3);
  allResults.push(siteResult);
  const dir = path.join(OUT, safe(target));
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, 'result.json'), JSON.stringify(siteResult, null, 2));
}

await browser.close();
await fs.writeFile(path.join(OUT, 'results.json'), JSON.stringify(allResults, null, 2));

const lines = ['# Leadscanner resultaten', '', `Scan: ${new Date().toISOString()}`, ''];
for (const site of allResults) {
  lines.push(`## ${site.target}`);
  lines.push(`- Browserkandidaat: ${site.candidate ? 'JA' : 'NEE / onvoldoende sterk'}`);
  if (site.lighthouse) lines.push(`- Lighthouse: ${JSON.stringify(site.lighthouse)}`);
  if (!site.topFindings.length) lines.push('- Geen sterke automatische bevindingen.');
  for (const f of site.topFindings) lines.push(`- [${f.profile}] ernst ${f.severity}/5 — ${f.type}: ${f.detail} (${f.url})`);
  lines.push('');
}
await fs.writeFile(path.join(OUT, 'summary.md'), lines.join('\n'));
console.log(`Klaar: ${urls.length} website(s) gescand. Resultaten staan in scan-results/.`);
