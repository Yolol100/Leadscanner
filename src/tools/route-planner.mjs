import { isDangerousActionUrl } from './network-safety.mjs';
import { isAllowedByRobots } from './discovery.mjs';

const bookingSignal = /(booking|boek(?:ing|en)?|afspraak|reserver|reservation|reserveer)/i;
const strongShopSignal = /(webshop|winkelwagen|checkout|afrekenen|\bcart\b|\/shop(?:\/|$)|\/winkel(?:\/|$))/i;
const productSignal = /(product|producten|shop|winkel|category|categorie)/i;
const serviceSignal = /(diensten?|services?|werkzaamheden|aanbod|specialismen?|schilderwerk|dakwerk|dakdekking|tuinaanleg|tuinonderhoud|installatie(?:techniek)?|loodgieter|elektra|verwarming|airco|renovatie)/i;
const contactSignal = /(contact|offerte|aanvraag|prijsopgave|vrijblijvend|contactformulier)/i;
const cartSignal = /(cart|winkelwagen)/i;
const checkoutSignal = /(checkout|afrekenen|bestellen)/i;
const ignoreLink = /(privacy|cookie|voorwaarden|disclaimer|login|inloggen|account|facebook|instagram|linkedin|youtube|whatsapp|mailto:|tel:|vacatur|stage|werken[\s-]?bij|carri[eè]re|career)/i;
const serviceNegative = /(contact|offerte|aanvraag|prijsopgave|vacatur|stage|werken[\s-]?bij|over[\s-]?ons|blog|nieuws|privacy|voorwaarden)/i;
const VALID_SITE_TYPES = new Set(['service', 'shop', 'booking']);

function sameOriginLinks(links, origin) {
  const seen = new Set();
  const out = [];
  for (const link of links || []) {
    const raw = String(link.href || '').split('#')[0];
    if (!raw || ignoreLink.test(`${link.text || ''} ${raw}`) || isDangerousActionUrl(raw)) continue;
    try {
      const u = new URL(raw);
      if (!['http:', 'https:'].includes(u.protocol) || u.origin !== origin) continue;
      const href = u.toString();
      if (seen.has(href)) continue;
      seen.add(href);
      out.push({ href, text: link.text || '', role_hint: link.role_hint || null, source: link.source || 'homepage' });
    } catch {}
  }
  return out;
}

function pickBest(links, regexes, used, negative = null, preferredRoles = []) {
  return links
    .filter((link) => !used.has(link.href))
    .map((link) => {
      const hay = `${link.text || ''} ${link.href}`;
      const roleBonus = preferredRoles.includes(link.role_hint) ? 40 : 0;
      const positive = regexes.reduce((sum, re, index) => sum + (re.test(hay) ? 12 - index : 0), 0);
      const penalty = negative && negative.test(hay) ? 25 : 0;
      const score = roleBonus + positive - penalty + Math.min(3, String(link.text || '').trim().length / 30);
      return { ...link, score };
    })
    .filter((link) => link.score > 0)
    .sort((a, b) => b.score - a.score)[0] || null;
}

export function detectSiteType(links = []) {
  const hay = links.map((link) => `${link.text || ''} ${link.href || ''}`).join(' ');
  return strongShopSignal.test(hay) ? 'shop' : bookingSignal.test(hay) ? 'booking' : 'service';
}

export function buildRoute({ homeUrl, links = [], discovery = null, siteTypeHint = '', maxPages = 4 } = {}) {
  const origin = new URL(homeUrl).origin;
  const homeInternal = sameOriginLinks(links, origin);
  const discovered = (discovery?.route_candidates || [])
    .filter((item) => item?.url && isAllowedByRobots(discovery?.robots_policy, item.url))
    .map((item) => ({ href: item.url, text: '', role_hint: item.role_hint || null, source: item.source || 'sitemap' }));
  const internal = sameOriginLinks([...homeInternal, ...discovered], origin);
  const detectedSiteType = detectSiteType(internal);
  const normalizedHint = String(siteTypeHint || '').trim().toLowerCase();
  const siteType = VALID_SITE_TYPES.has(normalizedHint) ? normalizedHint : detectedSiteType;
  const used = new Set([homeUrl]);
  const pages = [{ url: homeUrl, role: 'home', source: 'homepage' }];
  const add = (candidate, role) => {
    if (!candidate || pages.length >= maxPages) return;
    if (isDangerousActionUrl(candidate.href)) return;
    if (!isAllowedByRobots(discovery?.robots_policy, candidate.href)) return;
    used.add(candidate.href);
    pages.push({ url: candidate.href, role, source: candidate.source || 'homepage' });
  };

  if (siteType === 'shop') {
    add(pickBest(internal, [productSignal], used, null, ['product_or_category']), 'product_or_category');
    add(pickBest(internal, [cartSignal], used, null, ['cart']), 'cart');
    add(pickBest(internal, [checkoutSignal], used, null, ['checkout']), 'checkout');
  } else if (siteType === 'booking') {
    add(pickBest(internal, [serviceSignal, productSignal], used, serviceNegative, ['main_service', 'product_or_category']), 'offering');
    add(pickBest(internal, [bookingSignal], used, null, ['booking']), 'booking');
    add(pickBest(internal, [contactSignal], used, null, ['contact_or_quote']), 'contact');
  } else {
    const primaryService = pickBest(internal, [serviceSignal], used, serviceNegative, ['main_service'])
      || internal.find((link) => !used.has(link.href) && !serviceNegative.test(`${link.text || ''} ${link.href}`));
    add(primaryService, 'main_service');
    add(pickBest(internal, [contactSignal], used, null, ['contact_or_quote']), 'contact_or_quote');
  }

  if (pages.length === 1) add(internal.find((link) => !used.has(link.href)), 'important_internal');
  return { siteType, detectedSiteType, pages };
}

export function routeCoverage(routePlan = [], records = [], device) {
  if (!Array.isArray(routePlan) || !routePlan.length) return { complete: false, missing: ['route_plan'] };
  const pageRecords = (records || []).filter((record) => record.device === device && record.route_category !== 'full_route');
  const missing = [];
  for (const expected of routePlan) {
    const expectedUrl = new URL(expected.url).toString();
    const match = pageRecords.find((record) => {
      if (!record.planned_url) return false;
      let planned;
      try { planned = new URL(record.planned_url).toString(); } catch { return false; }
      return planned === expectedUrl && record.route_category === expected.role;
    });
    if (!match) missing.push(`${expected.role}:${expectedUrl}`);
  }
  return { complete: missing.length === 0, missing };
}
