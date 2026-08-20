import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { PlaywrightCrawler } from 'crawlee';
import { devices } from 'playwright';
import AxeBuilder from '@axe-core/playwright';
import { discoverSite, isAllowedByRobots } from './tools/discovery.mjs';
import { buildRoute, routeCoverage } from './tools/route-planner.mjs';
import { buildRequestFailureFinding } from './tools/runtime-signals.mjs';
import {
  assertPublicUrl,
  boundaryRespected,
  createBoundaryState,
  createRateLimiter,
  installPageSafety,
  isSameOfficialSite,
} from './tools/network-safety.mjs';

const OUT = path.resolve('scan-results');
const runLighthouse = String(process.env.RUN_LIGHTHOUSE || 'false').toLowerCase() === 'true';
const singleTarget = (process.env.TARGET_URL || '').trim();
const requireSingleTarget = String(process.env.REQUIRE_SINGLE_TARGET || 'false').toLowerCase() === 'true';
const siteTypeHint = String(process.env.SITE_TYPE_HINT || '').trim().toLowerCase();
const maxConcurrency = Math.max(1, Math.min(4, Number(process.env.MAX_CONCURRENCY || 2)));
const maxSiteStartsPerMinute = Math.max(1, Math.min(120, Number(process.env.MAX_REQUESTS_PER_MINUTE || 30)));
const maxActiveRequestsPerMinute = Math.max(30, Math.min(600, Number(process.env.MAX_ACTIVE_REQUESTS_PER_MINUTE || 120)));
const maxPagesPerSite = Math.max(2, Math.min(4, Number(process.env.MAX_PAGES_PER_SITE || 4)));
const runtimeSurface = 'github_actions_crawlee_playwright';
const MAX_FINDINGS_PER_PROFILE = 50;
const VALID_SITE_TYPES = new Set(['', 'service', 'shop', 'booking']);

if (requireSingleTarget && !singleTarget) throw new Error('TARGET_URL is verplicht voor een gecontroleerde single-site workflow_dispatch.');
if (!VALID_SITE_TYPES.has(siteTypeHint)) throw new Error('SITE_TYPE_HINT moet leeg, service, shop of booking zijn.');

const safe = (value) => value.replace(/^https?:\/\//, '').replace(/[^a-z0-9.-]+/gi, '_').replace(/_+/g, '_').slice(0, 100);
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  return value;
}
function evidence(payload) {
  const digest = sha256(JSON.stringify(stable(payload)));
  return { ...payload, evidence_sha256: digest, evidence_id: `evidence-${digest.slice(0, 12)}` };
}
function newBucket(profile) {
  return { profile, findings: [], pages: [], browser_evidence_records: [], _keys: new Set() };
}
function addFinding(bucket, finding) {
  if (bucket.findings.length >= MAX_FINDINGS_PER_PROFILE && (finding.severity || 0) < 5) return;
  const key = `${finding.type}|${finding.url}|${finding.detail}|${finding.device}`;
  if (bucket._keys.has(key)) return;
  bucket._keys.add(key);
  bucket.findings.push(finding);
}

await fs.rm(OUT, { recursive: true, force: true });
await fs.mkdir(OUT, { recursive: true });
const lines = singleTarget ? [] : (await fs.readFile('sites.txt', 'utf8')).split(/\r?\n/);
const urls = [...new Set((singleTarget ? [singleTarget] : lines)
  .map((value) => value.trim()).filter((value) => value && !value.startsWith('#'))
  .map((value) => /^https?:\/\//i.test(value) ? value : `https://${value}`))];
if (!urls.length) throw new Error('Geen websites gevonden.');

const placeholderRe = /\b(lorem ipsum|dummy text|placeholder|coming soon|under construction)\b/i;
const genericButtonRe = /^(button|knop|click here|klik hier|read more|lees meer)$/i;
const discoveryByTarget = new Map();
const preflightBlocked = new Map();
const boundaryByTarget = new Map();
const limiterByTarget = new Map();
const dnsCacheByTarget = new Map();

async function preflightTarget(target) {
  try {
    const dnsCache = new Map();
    await assertPublicUrl(target, { dnsCache });
    const discovery = await discoverSite(target);
    discoveryByTarget.set(target, discovery);
    dnsCacheByTarget.set(target, dnsCache);
    if (discovery.robots_policy?.access === 'blocked_temporarily') {
      preflightBlocked.set(target, 'robots.txt is tijdelijk onbereikbaar; scan fail-closed geblokkeerd.');
      return;
    }
    if (!isAllowedByRobots(discovery.robots_policy, target)) {
      preflightBlocked.set(target, 'robots.txt staat deze doel-URL niet toe voor Webactueel-Leadscanner.');
    }
  } catch (error) {
    preflightBlocked.set(target, `Publieke target-preflight geblokkeerd: ${String(error.message || error).slice(0, 260)}`);
  }
}
for (let offset = 0; offset < urls.length; offset += 4) {
  await Promise.all(urls.slice(offset, offset + 4).map(preflightTarget));
}

function wireSignals(page, target, profile, bucket, boundary) {
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const detail = msg.text().slice(0, 350);
    const noisy = /(failed to load resource|networkerror|net::err_|favicon)/i.test(detail);
    addFinding(bucket, { severity: noisy ? 1 : 2, type: 'console_error', url: page.url() || target, detail, device: profile, route_category: 'runtime' });
  });
  page.on('pageerror', (error) => addFinding(bucket, { severity: 3, type: 'javascript_error', url: page.url() || target, detail: String(error.message || error).slice(0, 350), device: profile, route_category: 'runtime' }));
  page.on('requestfailed', (request) => {
    const requestUrl = request.url();
    let sameOfficialSite = false;
    try {
      sameOfficialSite = isSameOfficialSite(requestUrl, target);
    } catch {
      return;
    }
    const finding = buildRequestFailureFinding({
      target,
      pageUrl: page.url() || target,
      requestUrl,
      resourceType: request.resourceType(),
      errorText: request.failure()?.errorText || 'network failure',
      sameOfficialSite,
    });
    if (finding) addFinding(bucket, { ...finding, device: profile });
  });
  page.on('response', (response) => {
    if (response.status() < 400) return;
    if (!isSameOfficialSite(response.url(), target)) {
      boundary.third_party_http_errors_ignored += 1;
      return;
    }
    const resource = response.request().resourceType();
    const status = response.status();
    if ([401, 403, 429].includes(status)) {
      addFinding(bucket, { severity: 1, type: 'access_blocker', url: page.url() || target, detail: `${status} ${resource}: ${response.url()}`, device: profile, route_category: 'runtime' });
      return;
    }
    addFinding(bucket, {
      severity: resource === 'document' ? 5 : ['script', 'stylesheet', 'image'].includes(resource) ? 3 : 1,
      type: 'http_error',
      url: page.url() || target,
      detail: `${status} ${resource}: ${response.url()}`,
      device: profile,
      route_category: 'runtime',
    });
  });
}

async function inspect(page, target, profile, role, plannedUrl, bucket) {
  const pageUrl = page.url();
  if (!isSameOfficialSite(pageUrl, target)) throw new Error(`Cross-site runtime-URL geblokkeerd: ${pageUrl}`);
  const title = await page.title().catch(() => '');
  const state = await page.evaluate(({ placeholderSource, genericSource }) => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const text = (document.body?.innerText || '').replace(/\s+/g, ' ').trim();
    const placeholder = new RegExp(placeholderSource, 'i');
    const generic = new RegExp(genericSource, 'i');
    return {
      textSample: text.slice(0, 12000),
      headings: [...document.querySelectorAll('h1,h2')].filter(visible).map((heading) => (heading.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 16),
      links: [...document.querySelectorAll('a[href]')].filter(visible).map((anchor) => ({ href: anchor.href, text: (anchor.innerText || anchor.getAttribute('aria-label') || '').trim() })).slice(0, 500),
      forms: [...document.forms].map((form) => ({ action: form.action, method: (form.method || 'get').toUpperCase(), fields: form.querySelectorAll('input,select,textarea').length })),
      brokenImages: [...document.images].filter((image) => image.complete && image.naturalWidth === 0 && visible(image)).slice(0, 10).map((image) => image.currentSrc || image.src),
      genericButtons: [...document.querySelectorAll('button,a')].filter(visible).map((element) => (element.innerText || element.getAttribute('aria-label') || '').trim()).filter((textValue) => generic.test(textValue)).slice(0, 10),
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
      for (const violation of axe.violations.filter((item) => item.impact === 'serious' || item.impact === 'critical').slice(0, 5)) {
        addFinding(bucket, { severity: violation.impact === 'critical' ? 4 : 3, type: 'accessibility', url: pageUrl, detail: `${violation.impact}: ${violation.help} (${violation.nodes.length} element(en))`, device: profile, route_category: role });
      }
    } catch (error) {
      addFinding(bucket, { severity: 1, type: 'axe_scan_error', url: pageUrl, detail: String(error.message || error).slice(0, 250), device: profile, route_category: role });
    }
  }

  const dir = path.join(OUT, safe(target));
  await fs.mkdir(dir, { recursive: true });
  const screenshotPath = path.join(dir, `${profile}-${role}-${safe(new URL(pageUrl).pathname || 'home')}.jpg`);
  await page.screenshot({ path: screenshotPath, type: 'jpeg', quality: 45, fullPage: false });
  const viewport = page.viewportSize();
  if (!viewport) throw new Error(`Geen viewport voor ${profile}`);
  const ev = evidence({
    evidence_kind: 'browser',
    source_type: 'controlled_browser_capture',
    device: profile,
    runtime_surface: runtimeSurface,
    canonical_url: target,
    runtime_url: pageUrl,
    planned_url: plannedUrl,
    route_category: role,
    route_complete: false,
    artifact_sha256: sha256(await fs.readFile(screenshotPath)),
    artifact_ref: path.relative(process.cwd(), screenshotPath),
    captured_at: new Date().toISOString(),
    viewport,
  });
  bucket.browser_evidence_records.push(ev);
  bucket.pages.push({ url: pageUrl, planned_url: plannedUrl, title, route_category: role, headings: state.headings, text_sample: state.textSample, forms: state.forms, links: state.links, evidence_id: ev.evidence_id });
  for (const finding of bucket.findings) {
    if (finding.url === pageUrl && finding.device === profile && !finding.evidence_ids) finding.evidence_ids = [ev.evidence_id];
  }
  return state.links;
}

async function visitRoute(page, target, profile, plan, bucket, skipFirst = false) {
  for (let index = skipFirst ? 1 : 0; index < plan.length; index += 1) {
    const item = plan[index];
    try {
      const response = await page.goto(item.url, { waitUntil: 'domcontentloaded', timeout: 25000 });
      if (response && [401, 403, 429].includes(response.status())) {
        addFinding(bucket, { severity: 1, type: 'access_blocker', url: item.url, detail: `Belangrijke pagina geeft HTTP ${response.status()}; dit is een scanblokkade, geen salesprobleem.`, device: profile, route_category: item.role });
      } else if (response && response.status() >= 400) {
        addFinding(bucket, { severity: 5, type: 'core_page_error', url: item.url, detail: `Belangrijke pagina geeft HTTP ${response.status()}.`, device: profile, route_category: item.role });
      }
      await page.waitForTimeout(index === 0 ? 700 : 350);
      await inspect(page, target, profile, item.role, item.url, bucket);
    } catch (error) {
      addFinding(bucket, { severity: 4, type: 'core_page_unreachable', url: item.url, detail: `Belangrijke pagina kon niet veilig worden geopend: ${String(error.message || error).slice(0, 220)}`, device: profile, route_category: item.role });
      bucket.pages.push({ url: item.url, planned_url: item.url, route_category: item.role, error: String(error.message || error).slice(0, 220) });
    }
  }
}

async function persistSite(site) {
  const dir = path.join(OUT, safe(site.target));
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, 'result.json'), JSON.stringify(site, null, 2));
}

async function scanSite(request, desktopPage) {
  const target = request.url;
  const boundary = boundaryByTarget.get(target) || createBoundaryState();
  const discovery = discoveryByTarget.get(target) || null;
  const desktop = newBucket('desktop');
  wireSignals(desktopPage, target, 'desktop', desktop, boundary);
  await desktopPage.waitForTimeout(700);
  const homeRuntimeUrl = desktopPage.url();
  const homeLinks = await inspect(desktopPage, target, 'desktop', 'home', homeRuntimeUrl, desktop);
  const route = buildRoute({ homeUrl: homeRuntimeUrl, links: homeLinks, discovery, siteTypeHint, maxPages: maxPagesPerSite });
  await visitRoute(desktopPage, target, 'desktop', route.pages, desktop, true);

  const mobile = newBucket('mobile');
  const browser = desktopPage.context().browser();
  if (browser) {
    const context = await browser.newContext({ ...devices['iPhone 13'] });
    try {
      const page = await context.newPage();
      await installPageSafety(page, {
        target,
        boundary,
        dnsCache: dnsCacheByTarget.get(target) || new Map(),
        activeLimiter: limiterByTarget.get(target),
      });
      wireSignals(page, target, 'mobile', mobile, boundary);
      await visitRoute(page, target, 'mobile', route.pages, mobile, false);
    } finally {
      await context.close().catch(() => {});
    }
  } else {
    addFinding(mobile, { severity: 4, type: 'mobile_runtime_unavailable', url: target, detail: 'Mobiele browsercontext niet beschikbaar.', device: 'mobile', route_category: 'runtime' });
  }

  const browserEvidenceRecords = [...desktop.browser_evidence_records, ...mobile.browser_evidence_records];
  const desktopCoverage = routeCoverage(route.pages, browserEvidenceRecords, 'desktop');
  const mobileCoverage = routeCoverage(route.pages, browserEvidenceRecords, 'mobile');
  const findings = [...desktop.findings, ...mobile.findings].sort((a, b) => (b.severity || 0) - (a.severity || 0));
  const topFindings = findings.slice(0, 3);
  const site = {
    inputIndex: request.userData.inputIndex,
    target,
    scannedAt: new Date().toISOString(),
    safe_boundary_respected: boundaryRespected(boundary),
    safety: boundary,
    site_type_hint: siteTypeHint || null,
    site_type_detected: route.detectedSiteType,
    site_type_used: route.siteType,
    route_plan: route.pages,
    route_coverage: { desktop: desktopCoverage, mobile: mobileCoverage },
    profiles: [desktop, mobile],
    browser_evidence_records: browserEvidenceRecords,
    desktop_evidence_ids: desktop.browser_evidence_records.map((item) => item.evidence_id),
    mobile_evidence_ids: mobile.browser_evidence_records.map((item) => item.evidence_id),
    topFindings,
    browser_route_complete: desktopCoverage.complete && mobileCoverage.complete,
    supplemental: { discovery, scoring_policy: 'supplemental_only_no_automatic_lead_score' },
  };
  site.candidate = site.browser_route_complete && topFindings.some((finding) => (finding.severity || 0) >= 3 && finding.type !== 'accessibility');
  await persistSite(site);
  return site;
}

async function maybeLighthouse(site) {
  if (!runLighthouse || !site.candidate) return null;
  const dir = path.join(OUT, safe(site.target));
  const out = path.join(dir, 'lighthouse.json');
  try {
    execFileSync('npx', ['lighthouse', site.target, '--quiet', '--output=json', `--output-path=${out}`, '--only-categories=performance,accessibility,best-practices,seo', '--chrome-flags=--headless --no-sandbox --disable-gpu'], { timeout: 90000, stdio: 'pipe' });
    const report = JSON.parse(await fs.readFile(out, 'utf8'));
    return Object.fromEntries(Object.entries(report.categories || {}).map(([key, value]) => [key, Math.round((value.score || 0) * 100)]));
  } catch (error) {
    return { error: String(error.message || error).slice(0, 300) };
  }
}

const resultsByTarget = new Map();
for (const [index, target] of urls.entries()) {
  if (preflightBlocked.has(target)) {
    const discovery = discoveryByTarget.get(target) || null;
    const site = {
      inputIndex: index,
      target,
      scannedAt: new Date().toISOString(),
      safe_boundary_respected: true,
      safety: { ...createBoundaryState(), preflight_only: true },
      browser_route_complete: false,
      candidate: false,
      scan_blocked_reason: preflightBlocked.get(target),
      browser_evidence_records: [],
      desktop_evidence_ids: [],
      mobile_evidence_ids: [],
      topFindings: [],
      profiles: [],
      supplemental: { discovery, scoring_policy: 'supplemental_only_no_automatic_lead_score' },
    };
    resultsByTarget.set(target, site);
    await persistSite(site);
  } else {
    boundaryByTarget.set(target, createBoundaryState());
    limiterByTarget.set(target, createRateLimiter(maxActiveRequestsPerMinute));
    if (!dnsCacheByTarget.has(target)) dnsCacheByTarget.set(target, new Map());
  }
}

const runnableUrls = urls.filter((target) => !preflightBlocked.has(target));
if (runnableUrls.length) {
  const crawler = new PlaywrightCrawler({
    headless: true,
    launchContext: { launchOptions: { headless: true } },
    maxConcurrency,
    maxRequestsPerMinute: maxSiteStartsPerMinute,
    maxRequestsPerCrawl: runnableUrls.length + 2,
    maxRequestRetries: 0,
    navigationTimeoutSecs: 30,
    requestHandlerTimeoutSecs: 180,
    preNavigationHooks: [async ({ page, request }, options) => {
      const target = request.url;
      await page.setViewportSize({ width: 1440, height: 900 });
      await installPageSafety(page, {
        target,
        boundary: boundaryByTarget.get(target),
        dnsCache: dnsCacheByTarget.get(target),
        activeLimiter: limiterByTarget.get(target),
      });
      options.waitUntil = 'domcontentloaded';
      options.timeout = 25000;
    }],
    async requestHandler({ request, page, log }) {
      log.info(`Scan ${request.userData.inputIndex + 1}/${urls.length}: ${request.url}`);
      resultsByTarget.set(request.url, await scanSite(request, page));
    },
    async failedRequestHandler({ request, log }, error) {
      const boundary = boundaryByTarget.get(request.url) || createBoundaryState();
      const site = {
        inputIndex: request.userData.inputIndex,
        target: request.url,
        scannedAt: new Date().toISOString(),
        safe_boundary_respected: boundaryRespected(boundary),
        safety: boundary,
        browser_route_complete: false,
        candidate: false,
        error: String(error?.message || error || 'scan mislukt').slice(0, 500),
        browser_evidence_records: [], desktop_evidence_ids: [], mobile_evidence_ids: [], topFindings: [], profiles: [],
        supplemental: { discovery: discoveryByTarget.get(request.url) || null, scoring_policy: 'supplemental_only_no_automatic_lead_score' },
      };
      log.error(`Scan mislukt: ${request.url}: ${site.error}`);
      resultsByTarget.set(request.url, site);
      await persistSite(site);
    },
  });
  await crawler.run(runnableUrls.map((url, inputIndex) => ({ url, uniqueKey: url, userData: { inputIndex: urls.indexOf(url) } })));
}

const results = urls.map((url, inputIndex) => resultsByTarget.get(url) || ({ inputIndex, target: url, candidate: false, browser_route_complete: false, safe_boundary_respected: false, error: 'Geen resultaat ontvangen.', browser_evidence_records: [], desktop_evidence_ids: [], mobile_evidence_ids: [], profiles: [], topFindings: [] }));
for (const site of results) {
  site.lighthouse = await maybeLighthouse(site);
  await persistSite(site);
}
await fs.writeFile(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
const summary = [
  '# Leadscanner resultaten', '',
  `Scan: ${new Date().toISOString()}`,
  `Websites: ${urls.length}`,
  `Crawlee maxConcurrency: ${maxConcurrency}`,
  `Website-starts per minuut: ${maxSiteStartsPerMinute}`,
  `Eerste-partij document/XHR/fetch-budget per minuut: ${maxActiveRequestsPerMinute}`,
  'Veilige grens: alleen publieke HTTP(S), alleen GET/HEAD, geen riskante actie-URLs, geen cross-site documentredirects en strikt TLS.',
  '',
];
for (const site of results) {
  summary.push(`## ${site.target}`);
  summary.push(`- Route compleet desktop+mobiel: ${site.browser_route_complete ? 'JA' : 'NEE'}`);
  summary.push(`- Safe boundary: ${site.safe_boundary_respected ? 'JA' : 'NEE'}`);
  if (site.site_type_used) summary.push(`- Sitetype gebruikt: ${site.site_type_used}${site.site_type_hint ? ` (Leads-hint: ${site.site_type_hint})` : ''}`);
  if (site.route_plan) summary.push(`- Kernroute: ${site.route_plan.map((page) => `${page.role}=${page.url}`).join(' -> ')}`);
  if (site.scan_blocked_reason) summary.push(`- Preflight blokkade: ${site.scan_blocked_reason}`);
  if (site.error) summary.push(`- Scanerror: ${site.error}`);
  for (const finding of site.topFindings || []) summary.push(`- [${finding.device}] ernst ${finding.severity}/5 — ${finding.type}: ${finding.detail}`);
  summary.push('');
}
await fs.writeFile(path.join(OUT, 'summary.md'), summary.join('\n'));
console.log(`Klaar: ${results.length} website(s) verwerkt; ${results.filter((result) => result.browser_route_complete).length} met exact complete desktop+mobiel route.`);
