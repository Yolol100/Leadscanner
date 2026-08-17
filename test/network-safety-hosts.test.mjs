import test from 'node:test';
import assert from 'node:assert/strict';
import { canonicalSiteHost, isSameOfficialSite, normalizeHost, siteIdentity } from '../src/tools/network-safety.mjs';

test('normalizes IDN hosts deterministically', () => {
  assert.equal(normalizeHost('https://münich.example/path'), 'xn--mnich-kva.example');
  assert.equal(siteIdentity('https://münich.example/').canonical_host, 'xn--mnich-kva.example');
});

test('treats www and subdomains as the same controlled official-site boundary', () => {
  assert.equal(canonicalSiteHost('https://www.example.nl'), 'example.nl');
  assert.equal(isSameOfficialSite('https://shop.example.nl/product', 'https://www.example.nl'), true);
  assert.equal(isSameOfficialSite('https://example.nl.evil.test/', 'https://example.nl'), false);
});

test('normalizes trailing dots without widening the boundary', () => {
  assert.equal(normalizeHost('Example.NL.'), 'example.nl');
  assert.equal(isSameOfficialSite('https://www.example.nl./', 'https://example.nl'), true);
  assert.equal(isSameOfficialSite('https://notexample.nl/', 'https://example.nl'), false);
});
