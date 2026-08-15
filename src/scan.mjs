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
const maxConcurrency = Math.max(1, Math.min(8, Number(process.env.MAX_CONCURRENCY || 4)));
const maxRequestsPerMinute = Math.max(1, Math.min(120, Number(process.env.MAX_REQUESTS_PER_MINUTE || 30)));
const maxPagesPerSite = Math.max(2, Math.min(4, Number(process.env.MAX_PAGES_PER_SITE || 4)));
const runtimeSurface = 'github_actions_crawlee_playwright';

const safe = (value) => value.replace(/^https?:\/\//, '').replace(/[^a-z0-9.-]+/gi, '_').replace(/_+/g, '_').slice(0, 100);
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  }
  return value;
}

function buildHashedEvidence(payload) {
  const digest = sha256(JSON.stringify(stable(payload)));
  return { ...payload, evidence_sha256: digest, evidence_id: `evidence-${digest.slice(0, 12)}` };
}

await fs.rm(OUT, { recursive: true, force: true });
await fs.mkdir(OUT, { recursive: true });

const fileLines = singleTarget ? [] : (await fs.readFile('sites.txt', 'utf8')).split(/\r?\n/);
const urls = [...new Set((singleTarget ? [singleTarget] : fileLines)
  .map((x) => x.trim())
  .filter((x) => x && !x.startsWith('#'))
  .map((x) => /^https?:\/\//i.test(x) ? x : `https://${x}`))];
if (!urls.length) throw new Error('Geen websites gevonden. Zet URLs in sites.txt of gebruik TARGET_URL.');

const placeholderRe = /\b(lorem ipsum|dummy text|placeholder|coming soon|under construction)\b/i;
const genericButtonRe = /^(button|knop|click here|klik hier|read more|lees meer)$/i;
const bookingSignal = /(booking|boek(?:ing|en)?|afspraak|reserver|reservation|reserveer)/i;
const strongShopSignal = /(webshop|winkelwagen|checkout|afrekenen|\bcart\b|\/shop(?:\/|$)|\/winkel(?:\/|$))/i;
const productSignal = /(product|producten|shop|winkel|category|categorie)/i;
const serviceSignal = /(dienst|diensten|service|services|werkzaamheden|aanbod|specialisme|oplossing)/i;
const contactSignal = /(contact|offerte|aanvraag|prijsopgave|advies|bel ons|neem contact)/i;
const cartSignal = /(cart|winkelwagen)/i;
const checkoutSignal = /(checkout|afrekenen|bestellen)/i;
const ignoreLink = /(privacy|cookie|voorwaarden|disclaimer|login|inloggen|account|facebook|instagram|linkedin|youtube|whatsapp|mailto:|tel:)/i;

function addFinding(bucket, finding) {
  const key = `${finding.type}|${finding.url}|${finding.detail}|${finding.device}`;
  if (!bucket._keys.has(key)) {
    bucket._keys.add(key);
    bucket.findings.push(finding);
  }
}

function sameOriginUrls(links, origin) {
  const seen = new Set();
  const out = [];
  for (const link of links) {
    const raw = String(link.href || '').split('#')[0];
    if (!raw || ignoreLink.test(`${link.text || ''} ${raw}`)) continue;
    try {
      const u = new URL(raw);
      if (!['http:', 'https:'].includes(u.protocol) || u.origin !== origin) continue;
      const normalized = u.toString();
      if (seen.has(normalized)) continue;
      seen.add(normalized);
      out.push({ ...link, href: normalized });
    } catch {}
  }
  return out;
}

function pickBest(links, regexes, used) {
  return links
    .filter((l) => !used.has(l.href))
    .map((l) => {
      const hay = `${l.text || ''} ${l.href}`;
      const score = regexes.reduce((sum, re, i) => sum + (re.test(hay) ? (10 - i) : 0), 0)
        + Math.min(4, (l.text || '').trim().length / 25);
      return { ...l, score };
    })
    .filter((l) => l.score > 0)
    .sort((a, b) => b.score - a.score)[0] || null;
}

function buildRoute(homeUrl, links) {
  const origin = new URL(homeUrl).origin;
  const internal = sameOriginUrls(links, origin);
  const haystack = internal.map((l) => `${l.text} ${l.href}`).join(' ');
  const siteType = strongShopSignal.test(haystack) ? 'shop' : (bookingSignal.test(haystack) ? 'booking' : 'service');
  const used = new Set([homeUrl]);
  const pages = [{ url: homeUrl, role: 'home' }];

  const add = (candidate, role) => {
    if (!candidate || pages.length >= maxPagesPerSite) return;
    used.add(candidate.href);
    pages.push({ url: candidate.href, role });
  };

  if (siteType === 'shop') {
    add(pickBest(internal, [productSignal], used), 'product_or_category');
    add(pickBest(internal, [cartSignal], used), 'cart');
    add(pickBest(internal, [checkoutSignal], used), 'checkout');
  } else if (siteType === 'booking') {
    add(pickBest(internal, [serviceSignal, productSignal], used), 'offering');
    add(pickBest(internal, [bookingSignal], used), 'booking');
    add(pickBest(internal, [contactSignal], used), 'contact');
  } else {
    add(pickBest(internal, [serviceSignal], used), 'main_service');
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

function wirePageSignals(page, target, profileName, bucket) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') addFinding(bucket, {
      severity: 2,
      type: 'console_error',
      url: page.url() || target,
      detail: msg.text().slice(0, 400),
      device: profileName,
      route_category: 'runtime',
    });
  });
  page.on('pageerror', (err) => addFinding(bucket, {
    severity: 3,
    type: 'javascript_error',
    url: page.url() || target,
    detail: String(err.message || err).slice(0, 400),
    device: profileName,
    route_category: 'runtime',
  }));
  page.on('response', (res) => {
    if (res.status() >= 400) {
      const resource = res.request().resourceType();
      const severity = resource === 'document' ? 5 : (['script', 'stylesheet', 'image'].includes(resource) ? 3 : 1);
      addFinding(bucket, {
        severity,
        type: 'http_error',
        url: page.url() || target,
        detail: `${res.status()} ${resource}: ${res.url()}`,
        device: profileName,
        route_category: 'runtime',
      });
    }
  });
}

async function inspectRenderedPage(page, target, profileName, routeRole, bucket) {
  const pageUrl = page.url();
  const title = await page.title().catch(() => '');
  const state = await page.evaluate(({ placeholderSource, genericButtonSource }) => {
    const visible = (el) => {
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
    };
    const text = (document.body?.innerText || '').replace(/\s+/g, ' ').trim();
    const placeholder = new RegExp(placeholderSource, 'i');
    const genericButton = new RegExp(genericButtonSource, 'i');
    const brokenImages = [...document.images]
      .filter((img) => img.complete && img.naturalWidth === 0 && visible(img))
      .slice(0, 10)
      .map((img) => img.currentSrc || img.src);
    const genericButtons = [...document.querySelectorAll('button, a')]
      .filter(visible)
      .map((el) => (el.innerText || el.getAttribute('aria-label') || '').trim())
      .filter((t) => genericButton.test(t))
      .slice(0, 10);
    const forms = [...document.forms].map((form) => ({
      action: form.action,
      method: (form.method || 'get').toUpperCase(),
      fields: [...form.querySelectorAll('input, select, textarea')].length,
    }));
    const links = [...document.querySelectorAll('a[href]')]
      .filter(visible)
      .map((a) => ({ href: a.href, text: (a.innerText || a.getAttribute('aria-label') || '').trim() }))
      .slice(0, 500);
    const headings = [...document.querySelectorAll('h1, h2')]
      .filter(visible)
      .map((h) => (h.innerText || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean)
      .slice(0, 12);
    return {
      textSample: text.slice(0, 6000),
      headings,
      hasPlaceholder: placeholder.test(text),
      brokenImages,
      genericButtons,
      forms,
      overflow: document.documentElement.scrollWidth > window.innerWidth + 5,
      links,
    };
  }, { placeholderSource: placeholderRe.source, genericButtonSource: genericButtonRe.source });

  if (state.overflow && profileName === 'mobile') addFinding(bucket, {
    severity: 4, type: 'mobile_overflow', url: pageUrl,
    detail: 'Pagina is breder dan het mobiele scherm; horizontaal scrollen is nodig.',
    device: profileName, route_category: routeRole,
  });
  if (state.brokenImages.length) addFinding(bucket, {
    severity: 3, type: 'broken_images', url: pageUrl,
    detail: `${state.brokenImages.length} zichtbare afbeelding(en) laden niet.`,
    device: profileName, route_category: routeRole,
  });
  if (state.hasPlaceholder) addFinding(bucket, {
    severity: 4, type: 'placeholder_content', url: pageUrl,
    detail: 'Zichtbare placeholder-/dummytekst aangetroffen.',
    device: profileName, route_category: routeRole,
  });
  if (state.genericButtons.length) addFinding(bucket, {
    severity: 3, type: 'generic_cta', url: pageUrl,
    detail: `Generieke knoptekst: ${state.genericButtons.join(', ')}`,
    device: profileName, route_category: routeRole,
  });

  try {
    const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
    for (const v of axe.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').slice(0, 5)) {
      addFinding(bucket, {
        severity: v.impact === 'critical' ? 4 : 3,
        type: 'accessibility',
        url: pageUrl,
        detail: `${v.impact}: ${v.help} (${v.nodes.length} element(en))`,
        device: profileName,
        route_category: routeRole,
      });
    }
  } catch (e) {
    addFinding(bucket, {
      severity: 1,
      type: 'axe_scan_error',
      url: pageUrl,
      detail: String(e.message || e).slice(0, 300),
      device: profileName,
      route_category: routeRole,
    });
  }

  const dir = path.join(OUT, safe(target));
  await fs.mkdir(dir, { recursive: true });
  const screenshotPath = path.join(dir, `${profileName}-${routeRole}-${safe(new URL(pageUrl).pathname || 'home')}.jpg`);
  await page.screenshot({ path: screenshotPath, type: 'jpeg', quality: 55, fullPage: false });
  const screenshotBytes = await fs.readFile(screenshotPath);
  const viewport = page.viewportSize();
  if (!viewport) throw new Error(`Geen viewport voor ${profileName} ${pageUrl}`);

  const evidence = buildHashedEvidence({
    evidence_kind: 'browser',
    source_type: 'controlled_browser_capture',
    device: profileName,
    runtime_surface: runtimeSurface,
    canonical_url: target,
    runtime_url: pageUrl,
    route_category: routeRole,
    route_complete: true,
    artifact_sha256: sha256(screenshotBytes),
    artifact_ref: path.relative(process.cwd(), screenshotPath),
    captured_at: new Date().toISOString(),
    viewport,
  });

  bucket.browser_evidence_records.push(evidence);
  bucket.pages.push({
    url: pageUrl,
    title,
    route_category: routeRole,
    headings: state.headings,
    text_sample: state.textSample,
    forms: state.forms,
    evidence_id: evidence.evidence_id,
  });
  for (const finding of bucket.findings) {
    if (finding.url === pageUrl && finding.device === profileName && !finding.evidence_ids) {
      finding.evidence_ids = [evidence.evidence_id];
    }
  }
  return { links: state.links, evidence };
}

async function navigateAndInspect(page, target, profileName, planPages, bucket) {
  for (let i = 0; i < planPages.length; i++) {
    const item = planPages[i];
    try {
      const response = await page.goto(item.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      if (response && response.status() >= 400) addFinding(bucket, {
        severity: 5,
        type: 'core_page_error',
        url: item.url,
        detail: `Belangrijke pagina geeft HTTP ${response.status()}.`,
        device: profileName,
        route_category: item.role,
      });
      await page.waitForTimeout(i === 0 ? 900 : 500);
      await inspectRenderedPage(page, target, profileName, item.role, bucket);
    } catch (e) {
      addFinding(bucket, {
        severity: 4,
        type: 'core_page_unreachable',
        url: item.url,
        detail: `Belangrijke pagina kon niet worden geopend: ${String(e.message || e).slice(0, 250)}`,
        device: profileName,
        route_category: item.role,
      });
      bucket.pages.push({ url: item.url, route_category: item.role, error: String(e.message || e).slice(0, 250) });
    }
  }
}

async function scanSite(request, desktopPage) {
  const target = request.url;
  const siteResult = {
    inputIndex: request.userData.inputIndex,
    target,
    scannedAt: new Date().toISOString(),
    safe_boundary_respected: true,
    browser_evidence_records: [],
    profiles: [],
  };

  const desktop = { profile: 'desktop', findings: [], pages: [], browser_evidence_records: [], _keys: new Set() };
  wirePageSignals(desktopPage, target, 'desktop', desktop);
  await desktopPage.waitForTimeout(900);
  const desktopHome = await inspectRenderedPage(desktopPage, target, 'desktop', 'home', desktop);
  const route = buildRoute(desktopPage.url(), desktopHome.links);
  siteResult.site_type_detected = route.siteType;
  siteResult.route_plan = route.pages;

  for (const item of route.pages.slice(1)) {
    try {
      const response = await desktopPage.goto(item.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      if (response && response.status() >= 400) addFinding(desktop, {
        severity: 5,
        type: 'core_page_error',
        url: item.url,
        detail: `Belangrijke pagina geeft HTTP ${response.status()}.`,
        device: 'desktop',
        route_category: item.role,
      });
      await desktopPage.waitForTimeout(500);
      await inspectRenderedPage(desktopPage, target, 'desktop', item.role, desktop);
    } catch (e) {
      addFinding(desktop, {
        severity: 4,
        type: 'core_page_unreachable',
        url: item.url,
        detail: `Belangrijke pagina kon niet worden geopend: ${String(e.message || e).slice(0, 250)}`,
        device: 'desktop',
        route_category: item.role,
      });
    }
  }

  const browser = desktopPage.context().browser();
  const mobile = { profile: 'mobile', findings: [], pages: [], browser_evidence_records: [], _keys: new Set() };
  if (!browser) {
    addFinding(mobile, {
      severity: 4,
      type: 'mobile_runtime_unavailable',
      url: target,
      detail: 'Mobiele browsercontext kon niet worden aangemaakt.',
      device: 'mobile',
      route_category: 'runtime',
    });
  } else {
    const context = await browser.newContext({ ...devices['iPhone 13'], ignoreHTTPSErrors: false });
    await context.route('**/*', async (routeRequest) => {
      const method = routeRequest.request().method().toUpperCase();
      if (method === 'GET' || method === 'HEAD') await routeRequest.continue();
      else await routeRequest.abort('blockedbyclient');
    });
    const mobilePage = await context.newPage();
    wirePageSignals(mobilePage, target, 'mobile', mobile);
    await navigateAndInspect(mobilePage, target, 'mobile', route.pages, mobile);
    await context.close();
  }

  delete desktop._keys;
  delete mobile._keys;
  siteResult.profiles.push(desktop, mobile);
  siteResult.browser_evidence_records = [...desktop.browser_evidence_records, ...mobile.browser_evidence_records];
  siteResult.desktop_evidence_ids = desktop.browser_evidence_records.map((e) => e.evidence_id);
  siteResult.mobile_evidence_ids = mobile.browser_evidence_records.map((e) => e.evidence_id);

  const findings = [...desktop.findings, ...mobile.findings];
  siteResult.topFindings = findings.sort((a, b) => b.severity - a.severity).slice(0, 3);
  siteResult.browser_route_complete = desktop.browser_evidence_records.length >= route.pages.length
    && mobile.browser_evidence_records.length >= route.pages.length;
  siteResult.candidate = siteResult.browser_route_complete && siteResult.topFindings.some((f) => f.severity >= 3);
  return siteResult;
}

async function maybeRunLighthouse(target, siteResult) {
  const maxSeverity = Math.max(0, ...siteResult.profiles.flatMap((p) => p.findings.map((f) => f.severity)));
  if (!runLighthouse || maxSeverity < 3) return null;
  const dir = path.join(OUT, safe(target));
  await fs.mkdir(dir, { recursive: true });
  const output = path.join(dir, 'lighthouse.json');
  try {
    execFileSync('npx', [
      'lighthouse', target, '--quiet', '--output=json', `--output-path=${output}`,
      '--only-categories=performance,accessibility,best-practices,seo',
      '--chrome-flags=--headless --no-sandbox --disable-gpu',
    ], { stdio: 'pipe', timeout: 90000 });
    const report = JSON.parse(await fs.readFile(output, 'utf8'));
    return Object.fromEntries(Object.entries(report.categories || {}).map(([k, v]) => [k, Math.round((v.score || 0) * 100)]));
  } catch (e) {
    return { error: String(e.message || e).slice(0, 400) };
  }
}

const resultsByTarget = new Map();
const crawler = new PlaywrightCrawler({
  headless: true,
  launchContext: { launchOptions: { headless: true } },
  maxConcurrency,
  maxRequestsPerMinute,
  maxRequestsPerCrawl: urls.length + 5,
  maxRequestRetries: 1,
  navigationTimeoutSecs: 35,
  requestHandlerTimeoutSecs: 240,
  preNavigationHooks: [async ({ page }, gotoOptions) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installReadOnlyRoute(page);
    gotoOptions.waitUntil = 'domcontentloaded';
    gotoOptions.timeout = 30000;
  }],
  async requestHandler({ request, page, log }) {
    log.info(`Scan ${request.userData.inputIndex + 1}/${urls.length}: ${request.url}`);
    const siteResult = await scanSite(request, page);
    resultsByTarget.set(request.url, siteResult);
    const dir = path.join(OUT, safe(request.url));
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(path.join(dir, 'result.json'), JSON.stringify(siteResult, null, 2));
  },
  async failedRequestHandler({ request, error, log }) {
    log.error(`Scan mislukt: ${request.url}: ${error?.message || error}`);
    resultsByTarget.set(request.url, {
      inputIndex: request.userData.inputIndex,
      target: request.url,
      scannedAt: new Date().toISOString(),
      safe_boundary_respected: true,
      browser_route_complete: false,
      candidate: false,
      error: String(error?.message || error).slice(0, 500),
      browser_evidence_records: [],
      desktop_evidence_ids: [],
      mobile_evidence_ids: [],
      topFindings: [],
      profiles: [],
    });
  },
});

await crawler.run(urls.map((url, inputIndex) => ({ url, uniqueKey: url, userData: { inputIndex } })));
const allResults = urls.map((url, inputIndex) => resultsByTarget.get(url) || ({
  inputIndex,
  target: url,
  candidate: false,
  browser_route_complete: false,
  error: 'Geen scanresultaat ontvangen.',
}));

for (const site of allResults) {
  if (!site.profiles) continue;
  site.lighthouse = await maybeRunLighthouse(site.target, site);
  const dir = path.join(OUT, safe(site.target));
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, 'result.json'), JSON.stringify(site, null, 2));
}

await fs.writeFile(path.join(OUT, 'results.json'), JSON.stringify(allResults, null, 2));
const lines = [
  '# Leadscanner resultaten',
  '',
  `Scan: ${new Date().toISOString()}`,
  `Websites: ${urls.length}`,
  `Crawlee maxConcurrency: ${maxConcurrency}`,
  'Veilige grens: alleen GET/HEAD; geen formulierverzending, bestelling, betaling of boekingsbevestiging.',
  '',
];
for (const site of allResults) {
  lines.push(`## ${site.target}`);
  lines.push(`- Route compleet desktop+mobiel: ${site.browser_route_complete ? 'JA' : 'NEE'}`);
  if (site.site_type_detected) lines.push(`- Gedetecteerd sitetype: ${site.site_type_detected}`);
  if (site.route_plan) lines.push(`- Belangrijkste route: ${site.route_plan.map((p) => `${p.role}=${p.url}`).join(' -> ')}`);
  lines.push(`- Browserkandidaat: ${site.candidate ? 'JA' : 'NEE / onvoldoende sterk'}`);
  if (site.lighthouse) lines.push(`- Lighthouse: ${JSON.stringify(site.lighthouse)}`);
  if (site.error) lines.push(`- Scanerror: ${site.error}`);
  if (!site.topFindings?.length) lines.push('- Geen sterke automatische bevindingen.');
  for (const f of site.topFindings || []) lines.push(`- [${f.device}] ernst ${f.severity}/5 — ${f.type}: ${f.detail} (${f.url})`);
  lines.push('');
}
await fs.writeFile(path.join(OUT, 'summary.md'), lines.join('\n'));
console.log(`Klaar: ${urls.length} website(s) via Crawlee + Playwright gescand. Resultaten staan in scan-results/.`);
