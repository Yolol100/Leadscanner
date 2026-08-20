import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const SCRIPT = path.resolve('src/leads-handoff.mjs');

function rawEvidence(id, device, routeCategory, plannedUrl) {
  return {
    evidence_id: id,
    evidence_sha256: '0'.repeat(64),
    evidence_kind: 'browser',
    source_type: 'controlled_browser_capture',
    device,
    runtime_surface: 'github_actions_crawlee_playwright',
    canonical_url: 'https://example.test/',
    runtime_url: plannedUrl,
    planned_url: plannedUrl,
    route_category: routeCategory,
    route_complete: false,
    artifact_sha256: '1'.repeat(64),
    artifact_ref: `scan-results/example/${id}.jpg`,
    captured_at: '2026-08-18T10:00:00.000Z',
    viewport: device === 'mobile' ? { width: 390, height: 844 } : { width: 1440, height: 900 },
  };
}

async function runGenerator({ mobileFindings = [], mobilePages = [] } = {}) {
  const tmp = await fsp.mkdtemp(path.join(os.tmpdir(), 'leadscanner-handoff-test-'));
  const out = path.join(tmp, 'scan-results');
  await fsp.mkdir(out, { recursive: true });
  const home = 'https://example.test/';
  const contact = 'https://example.test/contact';
  const routePlan = [
    { url: home, role: 'home', source: 'homepage' },
    { url: contact, role: 'contact_or_quote', source: 'homepage' },
  ];
  const browserEvidenceRecords = [
    rawEvidence('desktop-home', 'desktop', 'home', home),
    rawEvidence('desktop-contact', 'desktop', 'contact_or_quote', contact),
    rawEvidence('mobile-home', 'mobile', 'home', home),
    rawEvidence('mobile-contact', 'mobile', 'contact_or_quote', contact),
  ];
  const result = {
    target: home,
    scannedAt: '2026-08-18T10:00:00.000Z',
    safe_boundary_respected: true,
    safety: { enforced: true, unsafe_continued: 0 },
    site_type_hint: 'service',
    site_type_detected: 'service',
    site_type_used: 'service',
    route_plan: routePlan,
    profiles: [
      { profile: 'desktop', findings: [], pages: [] },
      { profile: 'mobile', findings: mobileFindings, pages: mobilePages },
    ],
    browser_evidence_records: browserEvidenceRecords,
    topFindings: [],
    supplemental: { scoring_policy: 'supplemental_only_no_automatic_lead_score' },
  };
  await fsp.writeFile(path.join(out, 'results.json'), `${JSON.stringify([result], null, 2)}\n`);
  execFileSync(process.execPath, [SCRIPT], { cwd: tmp, stdio: 'pipe' });
  const handoffs = JSON.parse(fs.readFileSync(path.join(out, 'leads-handoff.json'), 'utf8'));
  await fsp.rm(tmp, { recursive: true, force: true });
  return handoffs[0];
}

test('raw mobile HTTP 403 blocks full-route and ready claims even when screenshots exist', async () => {
  const handoff = await runGenerator({
    mobileFindings: [{
      severity: 1,
      type: 'access_blocker',
      url: 'https://example.test/contact',
      detail: 'Belangrijke pagina geeft HTTP 403; dit is een scanblokkade, geen salesprobleem.',
      device: 'mobile',
      route_category: 'contact_or_quote',
    }],
  });

  assert.equal(handoff.desktop_checked, true);
  assert.equal(handoff.mobile_checked, false);
  assert.equal(handoff.browser_route_complete, false);
  assert.equal(handoff.ready_for_leads_review, false);
  assert.match(handoff.desktop_evidence_id, /^evidence-[0-9a-f]{12}$/);
  assert.equal(handoff.mobile_evidence_id, null);

  const mobileFullRoute = handoff.browser_evidence_records.find((item) => item.device === 'mobile' && item.route_category === 'full_route');
  assert.ok(mobileFullRoute);
  assert.equal(mobileFullRoute.route_complete, false);
  assert.equal(mobileFullRoute.missing_route_steps.length, 0);
  assert.equal(mobileFullRoute.failed_route_steps.length, 1);
  assert.match(mobileFullRoute.failed_route_steps[0], /access_blocker/);
  assert.match(mobileFullRoute.failed_route_steps[0], /HTTP 403/);
});

test('raw page navigation error blocks full-route without needing a finding', async () => {
  const handoff = await runGenerator({
    mobilePages: [{
      url: 'https://example.test/contact',
      planned_url: 'https://example.test/contact',
      route_category: 'contact_or_quote',
      error: 'net::ERR_TOO_MANY_REDIRECTS',
    }],
  });

  assert.equal(handoff.mobile_checked, false);
  assert.equal(handoff.ready_for_leads_review, false);
  const mobileFullRoute = handoff.browser_evidence_records.find((item) => item.device === 'mobile' && item.route_category === 'full_route');
  assert.equal(mobileFullRoute.route_complete, false);
  assert.match(mobileFullRoute.failed_route_steps[0], /page_error/);
  assert.match(mobileFullRoute.failed_route_steps[0], /ERR_TOO_MANY_REDIRECTS/);
});

test('complete evidence with no raw route failures remains ready', async () => {
  const handoff = await runGenerator();
  assert.equal(handoff.desktop_checked, true);
  assert.equal(handoff.mobile_checked, true);
  assert.equal(handoff.browser_route_complete, true);
  assert.equal(handoff.ready_for_leads_review, true);
  const fullRoutes = handoff.browser_evidence_records.filter((item) => item.route_category === 'full_route');
  assert.equal(fullRoutes.length, 2);
  assert.ok(fullRoutes.every((item) => item.route_complete === true && item.failed_route_steps.length === 0));
});
