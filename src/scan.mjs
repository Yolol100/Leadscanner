import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { PlaywrightCrawler } from 'crawlee';
import { devices } from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const OUT = path.resolve('scan-results');
const runLighthouse = String(process.env.RUN_LIGHTHOUSE || 'false').toLowerCase() === 'true';
const singleTarget = (process.env.TARGET_URL || '').trim();
const maxConcurrency = Math.max(1, Math.min(4, Number(process.env.MAX_CONCURRENCY || 2)));
const maxRequestsPerMinute = Math.max(1, Math.min(120, Number(process.env.MAX_REQUESTS_PER_MINUTE || 30)));
const maxPagesPerSite = Math.max(2, Math.min(4, Number(process.env.MAX_PAGES_PER_SITE || 4)));
const runtimeSurface = 'github_actions_crawlee_playwright';
const MAX_FINDINGS_PER_PROFILE = 50;

const safe = (value) => value.replace(/^https?:\/\//, '').replace(/[^a-z0-9.-]+/gi, '_').replace(/_+/g, '_').slice(0, 100);
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map((k) => [k, stable(value[k])]));
  return value;
}
function evidence(payload) {
  const digest = sha256(JSON.stringify(stable(payload)));
  return { ...payload, evidence_sha256: digest, evidence_id: `evidence-${digest.slice(0, 12)}` };
}

await fs.rm(OUT, { recursive: true, force: true });
await fs.mkdir(OUT, { recursive: true });
const lines = singleTarget ? [] : (await fs.readFile('sites.txt', 'utf8')).split(/\r?\n/);
const urls = [...new Set((singleTarget ? [singleTarget] : lines)
  .map((x) => x.trim()).filter((x) => x && !x.startsWith('#'))
  .map((x) => /^https?:\/\//i.test(x) ? x : `https://${x}`))];
if (!urls.length) throw new Error('Geen websites gevonden.');

const placeholderRe = /\b(lorem ipsum|dummy text|placeholder|coming soon|under construction)\b/i;
const genericButtonRe = /^(button|knop|click here|klik hier|read more|lees meer)$/i;
const bookingSignal = /(booking|boek(?:ing|en)?|afspraak|reserver|reservation|reserveer)/i;
const strongShopSignal = /(webshop|winkelwagen|checkout|afrekenen|\bcart\b|\/shop(?:\/|$)|\/winkel(?:\/|$))/i;
const productSignal = /(product|producten|shop|winkel|category|categorie)/i;
const serviceSignal = /(diensten?|services?|werkzaamheden|aanbod|specialismen?|schilderwerk|dakwerk|dakdekking|tuinaanleg|tuinonderhoud|installatie(?:techniek)?|loodgieter|elektra|verwarming|airco|renovatie)/i;
const contactSignal = /(contact|offerte|aanvraag|prijsopgave|vrijblijvend|contactformulier)/i;
const cartSignal = /(cart|winkelwagen)/i;
const checkoutSignal = /(checkout|afrekenen|bestellen)/i;
const ignoreLink = /(privacy|cookie|voorwaarden|disclaimer|login|inloggen|account|facebook|instagram|linkedin|youtube|whatsapp|mailto:|tel:|vacatur|stage|werken[\s-]?bij|carri[eè]re|career)/i;
const serviceNegative = /(contact|offerte|aanvraag|prijsopgave|vacatur|stage|werken[\s-]?bij|over[\s-]?ons|blog|nieuws|privacy|voorwaarden)/i;

function newBucket(profile) {
  return { profile, findings: [], pages: [], browser_evidence_records: [], _keys: new Set() };
}
function addFinding(bucket, finding) {
  if (!bucket._keys) bucket._keys = new Set();
  if (!bucket.findings) bucket.findings = [];
  if (bucket.findings.length >= MAX_FINDINGS_PER_PROFILE && (finding.severity || 0) < 5) return;
  const key = `${finding.type}|${finding.url}|${finding.detail}|${finding.device}`;
  if (bucket._keys.has(key)) return;
  bucket._keys.add(key);
  bucket.findings.push(finding);
}
function sameOriginLinks(links, origin) {
  const seen = new Set();
  const out = [];
  for (const link of links) {
    const raw = String(link.href || '').split('#')[0];
    if (!raw || ignoreLink.test(`${link.text || ''} ${raw}`)) continue;
    try {
      const u = new URL(raw);
      if (!['http:', 'https:'].includes(u.protocol) || u.origin !== origin) continue;
      const href = u.toString();
      if (seen.has(href)) continue;
      seen.add(href);
      out.push({ href, text: link.text || '' });
    } catch {}
  }
  return out;
}
function pickBest(links, regexes, used, negative = null) {
  return links.filter((l) => !used.has(l.href)).map((l) => {
    const hay = `${l.text} ${l.href}`;
    const positive = regexes.reduce((sum, re, i) => sum + (re.test(hay) ? 12 - i : 0), 0);
    const penalty = negative && negative.test(hay) ? 25 : 0;
    const score = positive - penalty + Math.min(3, l.text.trim().length / 30);
    return { ...l, score };
  }).filter((l) => l.score > 0).sort((a, b) => b.score - a.score)[0] || null;
}
function buildRoute(homeUrl, links) {
  const origin = new URL(homeUrl).origin;
  const internal = sameOriginLinks(links, origin);
  const hay = internal.map((l) => `${l.text} ${l.href}`).join(' ');
  const siteType = strongShopSignal.test(hay) ? 'shop' : bookingSignal.test(hay) ? 'booking' : 'service';
  const used = new Set([homeUrl]);
  const pages = [{ url: homeUrl, role: 'home' }];
  const add = (candidate, role) => {
    if (!candidate || pages.length >= maxPagesPerSite) return;
    used.add(candidate.href); pages.push({ url: candidate.href, role });
  };
  if (siteType === 'shop') {
    add(pickBest(internal, [productSignal], used), 'product_or_category');
    add(pickBest(internal, [cartSignal], used), 'cart');
    add(pickBest(internal, [checkoutSignal], used), 'checkout');
  } else if (siteType === 'booking') {
    add(pickBest(internal, [serviceSignal, productSignal], used, serviceNegative), 'offering');
    add(pickBest(internal, [bookingSignal], used), 'booking');
    add(pickBest(internal, [contactSignal], used), 'contact');
  } else {
    const primaryService = pickBest(internal, [serviceSignal], used, serviceNegative)
      || internal.find((l) => !used.has(l.href) && !serviceNegative.test(`${l.text} ${l.href}`));
    add(primaryService, 'main_service');
    add(pickBest(internal, [contactSignal], used), 'contact_or_quote');
  }
  if (pages.length === 1) add(internal.find((l) => !used.has(l.href)), 'important_internal');
  return { siteType, pages };
}

async function installReadOnlyRoute(page) {
  await page.route('**/*', async (route) => {
    const method = route.request().method().toUpperCase();
    if (method === 'GET' || method === 'HEAD') await route.continue();
    else await route.abort('blockedbyclient');
  });
}
function wireSignals(page, target, profile, bucket) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') addFinding(bucket, { severity: 2, type: 'console_error', url: page.url() || target, detail: msg.text().slice(0, 350), device: profile, route_category: 'runtime' });
  });
  page.on('pageerror', (err) => addFinding(bucket, { severity: 3, type: 'javascript_error', url: page.url() || target, detail: String(err.message || err).slice(0, 350), device: profile, route_category: 'runtime' }));
  page.on('response', (res) => {
    if (res.status() < 400) return;
    const resource = res.request().resourceType();
    addFinding(bucket, { severity: resource === 'document' ? 5 : ['script', 'stylesheet', 'image'].includes(resource) ? 3 : 1, type: 'http_error', url: page.url() || target, detail: `${res.status()} ${resource}: ${res.url()}`, device: profile, route_category: 'runtime' });
  });
}

async function inspect(page, target, profile, role, bucket) {
  const pageUrl = page.url();
  const title = await page.title().catch(() => '');
  const state = await page.evaluate(({ placeholderSource, genericSource }) => {
    const visible = (el) => { const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0; };
    const text = (document.body?.innerText || '').replace(/\s+/g, ' ').trim();
    const placeholder = new RegExp(placeholderSource, 'i');
    const generic = new RegExp(genericSource, 'i');
    return {
      textSample: text.slice(0, 12000),
      headings: [...document.querySelectorAll('h1,h2')].filter(visible).map((h) => (h.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 16),
      links: [...document.querySelectorAll('a[href]')].filter(visible).map((a) => ({ href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim() })).slice(0, 500),
      forms: [...document.forms].map((f) => ({ action: f.action, method: (f.method || 'get').toUpperCase(), fields: f.querySelectorAll('input,select,textarea').length })),
      brokenImages: [...document.images].filter((img) => img.complete && img.naturalWidth === 0 && visible(img)).slice(0, 10).map((img) => img.currentSrc || img.src),
      genericButtons: [...document.querySelectorAll('button,a')].filter(visible).map((el) => (el.innerText || el.getAttribute('aria-label') || '').trim()).filter((t) => generic.test(t)).slice(0, 10),
      hasPlaceholder: placeholder.test(text),
      overflow: document.documentElement.scrollWidth > window.innerWidth + 5,
    };
  }, { placeholderSource: placeholderRe.source, genericSource: genericButtonRe.source });

  if (profile === 'mobile' && state.overflow) addFinding(bucket, { severity: 4, type: 'mobile_overflow', url: pageUrl, detail: 'Pagina is breder dan het mobiele scherm; horizontaal scrollen is nodig.', device: profile, route_category: role });
  if (state.brokenImages.length) addFinding(bucket, { severity: 3, type: 'broken_images', url: pageUrl, detail: `${state.brokenImages.length} zichtbare afbeelding(en) laden niet.`, device: profile, route_category: role });
  if (state.hasPlaceholder) addFinding(bucket, { severity: 4, type: 'placeholder_content', url: pageUrl, detail: 'Zichtbare placeholder-/dummytekst aangetroffen.', device: profile, route_category: role });
  if (state.genericButtons.length) addFinding(bucket, { severity: 3, type: 'generic_cta', url: pageUrl, detail: `Generieke knoptekst: ${state.genericButtons.join(', ')}`, device: profile, route_category: role });

  if (role === 'home') {
    try {
      const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
      for (const v of axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').slice(0, 5)) {
        addFinding(bucket, { severity: v.impact === 'critical' ? 4 : 3, type: 'accessibility', url: pageUrl, detail: `${v.impact}: ${v.help} (${v.nodes.length} element(en))`, device: profile, route_category: role });
      }
    } catch (e) {
      addFinding(bucket, { severity: 1, type: 'axe_scan_error', url: pageUrl, detail: String(e.message || e).slice(0, 250), device: profile, route_category: role });
    }
  }

  const dir = path.join(OUT, safe(target)); await fs.mkdir(dir, { recursive: true });
  const screenshotPath = path.join(dir, `${profile}-${role}-${safe(new URL(pageUrl).pathname || 'home')}.jpg`);
  await page.screenshot({ path: screenshotPath, type: 'jpeg', quality: 45, fullPage: false });
  const viewport = page.viewportSize(); if (!viewport) throw new Error(`Geen viewport voor ${profile}`);
  const ev = evidence({ evidence_kind: 'browser', source_type: 'controlled_browser_capture', device: profile, runtime_surface: runtimeSurface, canonical_url: target, runtime_url: pageUrl, route_category: role, route_complete: true, artifact_sha256: sha256(await fs.readFile(screenshotPath)), artifact_ref: path.relative(process.cwd(), screenshotPath), captured_at: new Date().toISOString(), viewport });
  bucket.browser_evidence_records.push(ev);
  bucket.pages.push({ url: pageUrl, title, route_category: role, headings: state.headings, text_sample: state.textSample, forms: state.forms, evidence_id: ev.evidence_id });
  for (const f of bucket.findings) if (f.url === pageUrl && f.device === profile && !f.evidence_ids) f.evidence_ids = [ev.evidence_id];
  return state.links;
}

async function visitRoute(page, target, profile, plan, bucket, skipFirst = false) {
  for (let i = skipFirst ? 1 : 0; i < plan.length; i++) {
    const item = plan[i];
    try {
      const res = await page.goto(item.url, { waitUntil: 'domcontentloaded', timeout: 25000 });
      if (res && res.status() >= 400) addFinding(bucket, { severity: 5, type: 'core_page_error', url: item.url, detail: `Belangrijke pagina geeft HTTP ${res.status()}.`, device: profile, route_category: item.role });
      await page.waitForTimeout(i === 0 ? 700 : 350);
      await inspect(page, target, profile, item.role, bucket);
    } catch (err) {
      addFinding(bucket, { severity: 4, type: 'core_page_unreachable', url: item.url, detail: `Belangrijke pagina kon niet worden geopend: ${String(err.message || err).slice(0, 220)}`, device: profile, route_category: item.role });
      bucket.pages.push({ url: item.url, route_category: item.role, error: String(err.message || err).slice(0, 220) });
    }
  }
}

async function persistSite(site) {
  const dir = path.join(OUT, safe(site.target)); await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, 'result.json'), JSON.stringify(site, null, 2));
}

async function scanSite(request, desktopPage) {
  const target = request.url;
  const desktop = newBucket('desktop'); wireSignals(desktopPage, target, 'desktop', desktop);
  await desktopPage.waitForTimeout(700);
  const homeLinks = await inspect(desktopPage, target, 'desktop', 'home', desktop);
  const route = buildRoute(desktopPage.url(), homeLinks);
  await visitRoute(desktopPage, target, 'desktop', route.pages, desktop, true);

  const mobile = newBucket('mobile');
  const browser = desktopPage.context().browser();
  if (browser) {
    const context = await browser.newContext({ ...devices['iPhone 13'], ignoreHTTPSErrors: true });
    try {
      await context.route('**/*', async (r) => ['GET', 'HEAD'].includes(r.request().method().toUpperCase()) ? r.continue() : r.abort('blockedbyclient'));
      const p = await context.newPage(); wireSignals(p, target, 'mobile', mobile);
      await visitRoute(p, target, 'mobile', route.pages, mobile, false);
    } finally { await context.close().catch(() => {}); }
  } else addFinding(mobile, { severity: 4, type: 'mobile_runtime_unavailable', url: target, detail: 'Mobiele browsercontext niet beschikbaar.', device: 'mobile', route_category: 'runtime' });

  const site = { inputIndex: request.userData.inputIndex, target, scannedAt: new Date().toISOString(), safe_boundary_respected: true, site_type_detected: route.siteType, route_plan: route.pages, profiles: [desktop, mobile] };
  site.browser_evidence_records = [...desktop.browser_evidence_records, ...mobile.browser_evidence_records];
  site.desktop_evidence_ids = desktop.browser_evidence_records.map((e) => e.evidence_id);
  site.mobile_evidence_ids = mobile.browser_evidence_records.map((e) => e.evidence_id);
  const findings = [...desktop.findings, ...mobile.findings].sort((a, b) => (b.severity || 0) - (a.severity || 0));
  site.topFindings = findings.slice(0, 3);
  site.browser_route_complete = desktop.browser_evidence_records.length >= route.pages.length && mobile.browser_evidence_records.length >= route.pages.length;
  site.candidate = site.browser_route_complete && site.topFindings.some((f) => (f.severity || 0) >= 3);
  await persistSite(site);
  return site;
}

async function maybeLighthouse(site) {
  if (!runLighthouse || !site.candidate) return null;
  const dir = path.join(OUT, safe(site.target)); const out = path.join(dir, 'lighthouse.json');
  try {
    execFileSync('npx', ['lighthouse', site.target, '--quiet', '--output=json', `--output-path=${out}`, '--only-categories=performance,accessibility,best-practices,seo', '--chrome-flags=--headless --no-sandbox --disable-gpu --ignore-certificate-errors'], { timeout: 90000, stdio: 'pipe' });
    const report = JSON.parse(await fs.readFile(out, 'utf8'));
    return Object.fromEntries(Object.entries(report.categories || {}).map(([k, v]) => [k, Math.round((v.score || 0) * 100)]));
  } catch (e) { return { error: String(e.message || e).slice(0, 300) }; }
}

const resultsByTarget = new Map();
const crawler = new PlaywrightCrawler({
  headless: true,
  launchContext: { launchOptions: { headless: true, args: ['--ignore-certificate-errors'] } },
  maxConcurrency,
  maxRequestsPerMinute,
  maxRequestsPerCrawl: urls.length + 2,
  maxRequestRetries: 0,
  navigationTimeoutSecs: 30,
  requestHandlerTimeoutSecs: 180,
  preNavigationHooks: [async ({ page }, opts) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installReadOnlyRoute(page);
    opts.waitUntil = 'domcontentloaded'; opts.timeout = 25000;
  }],
  async requestHandler({ request, page, log }) {
    log.info(`Scan ${request.userData.inputIndex + 1}/${urls.length}: ${request.url}`);
    resultsByTarget.set(request.url, await scanSite(request, page));
  },
  async failedRequestHandler({ request, log }, error) {
    const site = { inputIndex: request.userData.inputIndex, target: request.url, scannedAt: new Date().toISOString(), safe_boundary_respected: true, browser_route_complete: false, candidate: false, error: String(error?.message || error || 'scan mislukt').slice(0, 500), browser_evidence_records: [], desktop_evidence_ids: [], mobile_evidence_ids: [], topFindings: [], profiles: [] };
    log.error(`Scan mislukt: ${request.url}: ${site.error}`);
    resultsByTarget.set(request.url, site); await persistSite(site);
  },
});

await crawler.run(urls.map((url, inputIndex) => ({ url, uniqueKey: url, userData: { inputIndex } })));
const results = urls.map((url, inputIndex) => resultsByTarget.get(url) || ({ inputIndex, target: url, candidate: false, browser_route_complete: false, safe_boundary_respected: true, error: 'Geen resultaat ontvangen.', browser_evidence_records: [], desktop_evidence_ids: [], mobile_evidence_ids: [], profiles: [], topFindings: [] }));
for (const site of results) { site.lighthouse = await maybeLighthouse(site); await persistSite(site); }
await fs.writeFile(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
const summary = ['# Leadscanner resultaten', '', `Scan: ${new Date().toISOString()}`, `Websites: ${urls.length}`, `Crawlee maxConcurrency: ${maxConcurrency}`, 'Veilige grens: alleen GET/HEAD; geen formulierverzending, bestelling, betaling of boekingsbevestiging.', ''];
for (const site of results) {
  summary.push(`## ${site.target}`);
  summary.push(`- Route compleet desktop+mobiel: ${site.browser_route_complete ? 'JA' : 'NEE'}`);
  if (site.site_type_detected) summary.push(`- Sitetype: ${site.site_type_detected}`);
  if (site.route_plan) summary.push(`- Kernroute: ${site.route_plan.map((p) => `${p.role}=${p.url}`).join(' -> ')}`);
  if (site.error) summary.push(`- Scanerror: ${site.error}`);
  for (const f of site.topFindings || []) summary.push(`- [${f.device}] ernst ${f.severity}/5 — ${f.type}: ${f.detail}`);
  summary.push('');
}
await fs.writeFile(path.join(OUT, 'summary.md'), summary.join('\n'));
console.log(`Klaar: ${results.length} website(s) verwerkt; ${results.filter((r) => r.browser_route_complete).length} met complete desktop+mobiel route.`);
