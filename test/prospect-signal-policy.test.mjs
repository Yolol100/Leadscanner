import assert from 'node:assert/strict';
import test from 'node:test';
import { classifyProspectSignal, canClaimPreparedArtifact } from '../src/tools/prospect-signal-policy.mjs';

test('website_absent is bounded and fail-closed', () => {
  assert.equal(classifyProspectSignal({ type: 'website_absent', officialBusinessProfile: true, websiteLinkAbsent: true, publicBusinessEmailVerified: true }).decision, 'qualify');
  assert.equal(classifyProspectSignal({ type: 'website_absent', officialBusinessProfile: true, websiteLinkAbsent: true, publicBusinessEmailVerified: false }).decision, 'skip');
});

test('ads and inactive social are discovery-only', () => {
  assert.equal(classifyProspectSignal({ type: 'active_ads' }).decision, 'prioritize_discovery');
  assert.equal(classifyProspectSignal({ type: 'inactive_social' }).decision, 'prioritize_discovery');
});

test('llms.txt state is not standalone search visibility evidence', () => {
  assert.equal(classifyProspectSignal({ type: 'missing_llms_txt' }).decision, 'not_search_evidence');
  assert.equal(classifyProspectSignal({ type: 'broken_llms_txt' }).decision, 'not_search_evidence');
});

test('prepared artifact claim requires existence and verified readback', () => {
  assert.equal(canClaimPreparedArtifact({ exists: true, readbackVerified: true }), true);
  assert.equal(canClaimPreparedArtifact({ exists: true, readbackVerified: false }), false);
});
