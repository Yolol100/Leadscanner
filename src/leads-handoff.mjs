import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const OUT = path.resolve('scan-results');
const RUNTIME_SURFACE = 'controlled-browser';
const RUNTIME_DETAIL = 'github_actions_crawlee_playwright';
const SCORE_OWNER = 'Webactueel Leads Skill';

const ROUTE_CATEGORY_MAP = new Map([
  ['home', 'presentatie'],
  ['main_service', 'navigatie'],
  ['contact_or_quote', 'contact'],
  ['product_or_category', 'product'],
  ['cart', 'bestellen'],
  ['checkout', 'betalen'],
  ['offering', 'product'],
  ['booking', 'boeken'],
  ['contact', 'contact'],
  ['important_internal', 'navigatie'],
  ['runtime', 'runtime'],
  ['full_route', 'full_route'],
]);

const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const stable = (value) => {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  return value;
};
const evidence = (payload) => {
  const digest = sha256(JSON.stringify(stable(payload)));
  return { ...payload, evidence_sha256: digest, evidence_id: `evidence-${digest.slice(0, 12)}` };
};
const safe = (value) => String(value || '').replace(/^https?:\/\//, '').replace(/[^a-z0-9.-]+/gi, '_').replace(/_+/g, '_').slice(0, 100);

function normalizeRouteCategory(value) {
  const raw = String(value || '').trim().toLowerCase();
  if (ROUTE_CATEGORY_MAP.has(raw)) return ROUTE_CATEGORY_MAP.get(raw);
  return raw.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim() || 'runtime';
}

function canonicalDomain(target) {
  const host = new URL(target).hostname.toLowerCase().replace(/\.$/, '');
  return host.startsWith('www.') ? host.slice(4) : host;
}

function leadIdForTarget(target) {
  return `lead-${sha256(canonicalDomain(target)).slice(0, 12)}`;
}

function adaptBrowserRecord(record) {
  const { evidence_id: oldId, evidence_sha256: _oldHash, ...payload } = record;
  const routeCategory = normalizeRouteCategory(payload.route_category);
  const adapted = evidence({
    ...payload,
    runtime_surface: RUNTIME_SURFACE,
    runtime_detail: RUNTIME_DETAIL,
    route_category: routeCategory,
    route_complete: routeCategory === 'full_route' ? Boolean(payload.route_complete) : false,
  });
  return { oldId, adapted };
}

function remapFinding(finding, idMap, recordByOldId) {
  const oldIds = finding.evidence_ids || [];
  const mappedIds = oldIds.map((id) => idMap.get(id)).filter(Boolean);
  const evidenceRecords = oldIds.map((id) => recordByOldId.get(id)).filter(Boolean);
  const evidenceRoute = evidenceRecords[0]?.route_category;
  return {
    source: 'leadscanner_browser_candidate',
    requires_leads_validation: true,
    automatic_score_effect: false,
    evidence_usable: mappedIds.length > 0,
    severity_hint: finding.severity ?? null,
    scanner_type: finding.type || null,
    detail: finding.detail || null,
    url: finding.url || null,
    device: finding.device || null,
    route_category: evidenceRoute || normalizeRouteCategory(finding.route_category),
    evidence_ids: mappedIds,
  };
}

function deviceRouteCoverage(site, adaptedRecords, device) {
  const expected = Array.isArray(site.route_plan) ? site.route_plan : [];
  const pageRecords = adaptedRecords.filter((record) => record.device === device && record.route_category !== 'full_route');
  const matched = [];
  const missing = [];
  for (const item of expected) {
    const expectedUrl = new URL(item.url).toString();
    const expectedCategory = normalizeRouteCategory(item.role);
    const match = pageRecords.find((record) => {
      if (!record.planned_url) return false;
      let planned;
      try { planned = new URL(record.planned_url).toString(); } catch { return false; }
      return planned === expectedUrl && record.route_category === expectedCategory;
    });
    if (match) matched.push(match.evidence_id);
    else missing.push(`${expectedCategory}:${expectedUrl}`);
  }
  return { complete: expected.length > 0 && missing.length === 0, matched, missing };
}

async function buildFullRouteEvidence(site, adaptedRecords, device) {
  const records = adaptedRecords.filter((record) => record.device === device && record.route_category !== 'full_route');
  if (!records.length) return null;
  const coverage = deviceRouteCoverage(site, adaptedRecords, device);
  const dir = path.join(OUT, safe(site.target));
  await fs.mkdir(dir, { recursive: true });
  const manifest = {
    format: 'leadscanner-route-manifest/1.2',
    target: site.target,
    lead_id: leadIdForTarget(site.target),
    device,
    route_plan: site.route_plan || [],
    page_evidence_ids: coverage.matched,
    missing_route_steps: coverage.missing,
    route_complete: coverage.complete,
    source_run_id: process.env.GITHUB_RUN_ID ? `github-actions-${process.env.GITHUB_RUN_ID}` : 'local-run',
    generated_at: new Date().toISOString(),
  };
  const bytes = `${JSON.stringify(manifest, null, 2)}\n`;
  const artifactPath = path.join(dir, `${device}-full-route.json`);
  await fs.writeFile(artifactPath, bytes);
  const capturedAt = records.map((record) => record.captured_at).filter(Boolean).sort().at(-1) || site.scannedAt || new Date().toISOString();
  return evidence({
    evidence_kind: 'browser',
    source_type: 'controlled_browser_capture',
    device,
    runtime_surface: RUNTIME_SURFACE,
    runtime_detail: RUNTIME_DETAIL,
    canonical_url: site.target,
    runtime_url: site.target,
    planned_url: site.target,
    route_category: 'full_route',
    route_complete: coverage.complete,
    artifact_sha256: sha256(bytes),
    artifact_ref: path.relative(process.cwd(), artifactPath),
    captured_at: capturedAt,
    viewport: records[0].viewport,
    page_evidence_ids: coverage.matched,
    missing_route_steps: coverage.missing,
  });
}

const results = JSON.parse(await fs.readFile(path.join(OUT, 'results.json'), 'utf8'));
const handoffs = [];

for (const site of results) {
  const adaptedPairs = (site.browser_evidence_records || []).map(adaptBrowserRecord);
  const idMap = new Map(adaptedPairs.map(({ oldId, adapted }) => [oldId, adapted.evidence_id]));
  const recordByOldId = new Map(adaptedPairs.map(({ oldId, adapted }) => [oldId, adapted]));
  const adaptedRecords = adaptedPairs.map(({ adapted }) => adapted);
  const desktopRoute = await buildFullRouteEvidence(site, adaptedRecords, 'desktop');
  const mobileRoute = await buildFullRouteEvidence(site, adaptedRecords, 'mobile');
  const browserEvidenceRecords = [...adaptedRecords, ...[desktopRoute, mobileRoute].filter(Boolean)];
  const desktopChecked = Boolean(desktopRoute?.route_complete);
  const mobileChecked = Boolean(mobileRoute?.route_complete);
  const browserRouteComplete = desktopChecked && mobileChecked;
  const ready = Boolean(site.safe_boundary_respected && browserRouteComplete);
  const handoff = {
    format: 'webactueel-leadscanner-handoff/1.1',
    repository: 'Yolol100/Leadscanner',
    workflow: '.github/workflows/scan.yml',
    source_run_id: process.env.GITHUB_RUN_ID ? `github-actions-${process.env.GITHUB_RUN_ID}` : 'local-run',
    lead_id: leadIdForTarget(site.target),
    target: site.target,
    site_type_hint: site.site_type_hint || null,
    site_type_detected: site.site_type_detected || null,
    site_type_used: site.site_type_used || null,
    site_type_requires_leads_confirmation: true,
    route_plan: site.route_plan || [],
    checked_on: String(site.scannedAt || new Date().toISOString()).slice(0, 10),
    runtime_surface: RUNTIME_SURFACE,
    runtime_detail: RUNTIME_DETAIL,
    safe_boundary_respected: Boolean(site.safe_boundary_respected),
    safety: site.safety || null,
    browser_route_complete: browserRouteComplete,
    desktop_checked: desktopChecked,
    mobile_checked: mobileChecked,
    browser_evidence_records: browserEvidenceRecords,
    desktop_evidence_id: desktopChecked ? desktopRoute.evidence_id : null,
    mobile_evidence_id: mobileChecked ? mobileRoute.evidence_id : null,
    finding_candidates: (site.topFindings || []).map((finding) => remapFinding(finding, idMap, recordByOldId)),
    supplemental: { ...(site.supplemental || {}), lighthouse: site.lighthouse || null, scoring_policy: 'supplemental_only_no_automatic_lead_score' },
    scoring: { owner: SCORE_OWNER, performed_by_repository: false, priority: null, qualified: null },
    merge_contract: {
      scanner_provides: ['lead_id', 'target', 'checked_on', 'runtime_surface', 'desktop_checked', 'mobile_checked', 'safe_boundary_respected', 'safety', 'browser_evidence_records', 'desktop_evidence_id', 'mobile_evidence_id', 'finding_candidates', 'supplemental'],
      required_from_leads: ['TARGET_SPEC context', 'company_name', 'region', 'site_type confirmation', 'official_confirmed', 'official_company_evidence', 'webactueel_fit', 'fit_reason', 'fit_evidence_ids', 'validated_observations_max_3'],
    },
    ready_for_leads_review: ready,
    missing_for_final_leads_score: ['company_name', 'region', 'site_type confirmation', 'official_confirmed', 'official_company_evidence', 'webactueel_fit', 'fit_reason', 'fit_evidence_ids', 'validated_observations_max_3'],
  };
  const dir = path.join(OUT, safe(site.target));
  await fs.writeFile(path.join(dir, 'leads-handoff.json'), `${JSON.stringify(handoff, null, 2)}\n`);
  handoffs.push(handoff);
}

await fs.writeFile(path.join(OUT, 'leads-handoff.json'), `${JSON.stringify(handoffs, null, 2)}\n`);
console.log(`Leads handoff gebouwd voor ${handoffs.length} website(s); ${handoffs.filter((item) => item.ready_for_leads_review).length} exact browser-compleet.`);
