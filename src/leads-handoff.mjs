import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const OUT = path.resolve('scan-results');
const RUNTIME_SURFACE = 'controlled-browser';
const RUNTIME_DETAIL = 'github_actions_crawlee_playwright';
const SCORE_OWNER = 'Webactueel Leads Skill';

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

function adaptBrowserRecord(record) {
  const { evidence_id: oldId, evidence_sha256: _oldHash, ...payload } = record;
  const adapted = evidence({ ...payload, runtime_surface: RUNTIME_SURFACE, runtime_detail: RUNTIME_DETAIL });
  return { oldId, adapted };
}

function remapFinding(finding, idMap) {
  const mappedIds = (finding.evidence_ids || []).map((id) => idMap.get(id)).filter(Boolean);
  return {
    source: 'leadscanner_browser_candidate',
    requires_leads_validation: true,
    automatic_score_effect: false,
    severity_hint: finding.severity ?? null,
    scanner_type: finding.type || null,
    detail: finding.detail || null,
    url: finding.url || null,
    device: finding.device || null,
    route_category: finding.route_category || null,
    evidence_ids: mappedIds,
  };
}

async function buildFullRouteEvidence(site, adaptedRecords, device) {
  const records = adaptedRecords.filter((record) => record.device === device);
  if (!records.length) return null;
  const dir = path.join(OUT, safe(site.target));
  await fs.mkdir(dir, { recursive: true });
  const manifest = {
    format: 'leadscanner-route-manifest/1.0',
    target: site.target,
    device,
    route_plan: site.route_plan || [],
    page_evidence_ids: records.map((record) => record.evidence_id),
    browser_route_complete: Boolean(site.browser_route_complete),
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
    route_category: 'full_route',
    route_complete: Boolean(site.browser_route_complete),
    artifact_sha256: sha256(bytes),
    artifact_ref: path.relative(process.cwd(), artifactPath),
    captured_at: capturedAt,
    viewport: records[0].viewport,
    page_evidence_ids: records.map((record) => record.evidence_id),
  });
}

const results = JSON.parse(await fs.readFile(path.join(OUT, 'results.json'), 'utf8'));
const handoffs = [];

for (const site of results) {
  const adaptedPairs = (site.browser_evidence_records || []).map(adaptBrowserRecord);
  const idMap = new Map(adaptedPairs.map(({ oldId, adapted }) => [oldId, adapted.evidence_id]));
  const adaptedRecords = adaptedPairs.map(({ adapted }) => adapted);
  const desktopRoute = await buildFullRouteEvidence(site, adaptedRecords, 'desktop');
  const mobileRoute = await buildFullRouteEvidence(site, adaptedRecords, 'mobile');
  const browserEvidenceRecords = [...adaptedRecords, ...[desktopRoute, mobileRoute].filter(Boolean)];
  const ready = Boolean(site.browser_route_complete && desktopRoute?.route_complete && mobileRoute?.route_complete);
  const handoff = {
    format: 'webactueel-leadscanner-handoff/1.0',
    repository: 'Yolol100/Leadscanner',
    workflow: '.github/workflows/scan.yml',
    source_run_id: process.env.GITHUB_RUN_ID ? `github-actions-${process.env.GITHUB_RUN_ID}` : 'local-run',
    target: site.target,
    site_type_detected: site.site_type_detected || null,
    route_plan: site.route_plan || [],
    checked_on: String(site.scannedAt || new Date().toISOString()).slice(0, 10),
    runtime_surface: RUNTIME_SURFACE,
    runtime_detail: RUNTIME_DETAIL,
    safe_boundary_respected: Boolean(site.safe_boundary_respected),
    browser_route_complete: Boolean(site.browser_route_complete),
    browser_evidence_records: browserEvidenceRecords,
    desktop_evidence_id: ready ? desktopRoute.evidence_id : null,
    mobile_evidence_id: ready ? mobileRoute.evidence_id : null,
    finding_candidates: (site.topFindings || []).map((finding) => remapFinding(finding, idMap)),
    supplemental: {
      ...(site.supplemental || {}),
      lighthouse: site.lighthouse || null,
      scoring_policy: 'supplemental_only_no_automatic_lead_score',
    },
    scoring: {
      owner: SCORE_OWNER,
      performed_by_repository: false,
      priority: null,
      qualified: null,
    },
    ready_for_leads_review: ready,
    missing_for_final_leads_score: [
      'lead_id',
      'company_name',
      'region',
      'official_confirmed',
      'official_company_evidence',
      'webactueel_fit',
      'fit_reason',
      'fit_evidence_ids',
      'validated_observations_max_3',
    ],
  };
  const dir = path.join(OUT, safe(site.target));
  await fs.writeFile(path.join(dir, 'leads-handoff.json'), `${JSON.stringify(handoff, null, 2)}\n`);
  handoffs.push(handoff);
}

await fs.writeFile(path.join(OUT, 'leads-handoff.json'), `${JSON.stringify(handoffs, null, 2)}\n`);
console.log(`Leads handoff gebouwd voor ${handoffs.length} website(s); ${handoffs.filter((item) => item.ready_for_leads_review).length} browser-compleet.`);
