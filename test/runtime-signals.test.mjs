import assert from 'node:assert/strict';
import test from 'node:test';
import { buildRequestFailureFinding } from '../src/tools/runtime-signals.mjs';

test('ignores expected browser aborts and third-party failures', () => {
  assert.equal(buildRequestFailureFinding({ target: 'https://example.com', pageUrl: 'https://example.com', requestUrl: 'https://example.com/image.jpg', resourceType: 'image', errorText: 'net::ERR_ABORTED', sameOfficialSite: true }), null);
  assert.equal(buildRequestFailureFinding({ target: 'https://example.com', pageUrl: 'https://example.com', requestUrl: 'https://example.com/tracker.js', resourceType: 'script', errorText: 'net::ERR_BLOCKED_BY_CLIENT', sameOfficialSite: true }), null);
  assert.equal(buildRequestFailureFinding({ target: 'https://example.com', pageUrl: 'https://example.com', requestUrl: 'https://cdn.example.net/app.js', resourceType: 'script', errorText: 'net::ERR_FAILED', sameOfficialSite: false }), null);
});

test('records first-party network failures without turning subresources into high-severity lead evidence', () => {
  const subresource = buildRequestFailureFinding({ target: 'https://example.com', pageUrl: 'https://example.com', requestUrl: 'https://example.com/app.js', resourceType: 'script', errorText: 'net::ERR_FAILED', sameOfficialSite: true });
  assert.equal(subresource?.type, 'network_request_failed');
  assert.equal(subresource?.severity, 2);

  const document = buildRequestFailureFinding({ target: 'https://example.com', pageUrl: 'https://example.com/pricing', requestUrl: 'https://example.com/pricing', resourceType: 'document', errorText: 'net::ERR_CONNECTION_RESET', sameOfficialSite: true });
  assert.equal(document?.severity, 4);
});
