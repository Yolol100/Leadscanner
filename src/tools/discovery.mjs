import { isDangerousActionUrl, isSameOfficialSite, safeFetchText, USER_AGENT } from './network-safety.mjs';

const DEFAULT_TIMEOUT_MS = 10000;
const MAX_TEXT_BYTES = 2_000_000;
const PRODUCT_TOKEN = 'webactueel-leadscanner';

function decodeXml(value) {
  return String(value)
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'");
}

export function parseSitemapXml(xml) {
  const urls = [];
  const re = /<loc\b[^>]*>([\s\S]*?)<\/loc>/gi;
  let match;
  while ((match = re.exec(String(xml)))) {
    const value = decodeXml(match[1].trim());
    if (/^https?:\/\//i.test(value)) urls.push(value);
  }
  return [...new Set(urls)];
}

export function parseRobotsSitemaps(text, origin) {
  const values = [];
  for (const rawLine of String(text).split(/\r?\n/)) {
    const line = rawLine.replace(/\s+#.*$/, '').trim();
    const match = line.match(/^sitemap\s*:\s*(\S+)\s*$/i);
    if (!match) continue;
    try { values.push(new URL(match[1], origin).toString()); } catch {}
  }
  return [...new Set(values)];
}

function robotsPatternRegex(pattern) {
  const anchored = pattern.endsWith('$');
  const body = anchored ? pattern.slice(0, -1) : pattern;
  const escaped = body.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}${anchored ? '$' : ''}`);
}

export function parseRobotsPolicy(text, productToken = PRODUCT_TOKEN) {
  const groups = [];
  let group = { agents: [], rules: [] };
  const flush = () => {
    if (group.agents.length) groups.push(group);
    group = { agents: [], rules: [] };
  };
  for (const rawLine of String(text).split(/\r?\n/)) {
    const line = rawLine.replace(/\s+#.*$/, '').trim();
    if (!line) continue;
    const separator = line.indexOf(':');
    if (separator < 0) continue;
    const field = line.slice(0, separator).trim().toLowerCase();
    const value = line.slice(separator + 1).trim();
    if (field === 'user-agent') {
      if (group.rules.length) flush();
      group.agents.push(value.toLowerCase());
      continue;
    }
    if ((field === 'allow' || field === 'disallow') && group.agents.length) {
      if (field === 'disallow' && value === '') continue;
      group.rules.push({ directive: field, pattern: value });
    }
  }
  flush();
  const token = String(productToken || PRODUCT_TOKEN).toLowerCase();
  const exact = groups.filter((candidate) => candidate.agents.some((agent) => agent === token));
  const wildcard = groups.filter((candidate) => candidate.agents.includes('*'));
  const selected = exact.length ? exact : wildcard;
  return {
    product_token: token,
    selected_rules: selected.flatMap((candidate) => candidate.rules),
    group_count: groups.length,
  };
}

export function isAllowedByRobots(policy, value) {
  if (!policy) return true;
  if (policy.access === 'blocked_temporarily') return false;
  const rules = Array.isArray(policy.selected_rules) ? policy.selected_rules : [];
  if (!rules.length) return true;
  let path;
  try {
    const parsed = new URL(value);
    path = `${parsed.pathname}${parsed.search}` || '/';
  } catch {
    return false;
  }
  const matches = [];
  for (const rule of rules) {
    if (!rule.pattern) continue;
    try {
      if (robotsPatternRegex(rule.pattern).test(path)) matches.push(rule);
    } catch {}
  }
  if (!matches.length) return true;
  matches.sort((a, b) => b.pattern.length - a.pattern.length || (a.directive === 'allow' ? -1 : 1));
  const longest = matches[0].pattern.length;
  const tied = matches.filter((rule) => rule.pattern.length === longest);
  if (tied.some((rule) => rule.directive === 'allow')) return true;
  return tied[0].directive !== 'disallow';
}

function classify(url) {
  const parsed = new URL(url);
  const value = parsed.pathname.toLowerCase();
  if (isDangerousActionUrl(url)) return 'other';
  if (/(contact|offerte|aanvraag|prijsopgave)/.test(value)) return 'contact_or_quote';
  if (/(checkout|afrekenen)/.test(value)) return 'checkout';
  if (/(winkelwagen|\/cart(?:\/|$))/.test(value)) return 'cart';
  if (/(boek|booking|afspraak|reserver)/.test(value)) return 'booking';
  if (/(product|shop|winkel|categorie|category)/.test(value)) return 'product_or_category';
  if (/(dienst|service|werkzaam|schilder|dak|tuin|install|loodgiet|elektra|verwarm|airco|renov)/.test(value)) return 'main_service';
  return 'other';
}

export async function discoverSite(target, { maxSitemaps = 4, maxUrls = 300, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const origin = new URL(target).origin;
  const dnsCache = new Map();
  const result = {
    source: 'robots+sitemap',
    user_agent: USER_AGENT,
    robots_url: new URL('/robots.txt', origin).toString(),
    robots_status: null,
    robots_policy: { product_token: PRODUCT_TOKEN, selected_rules: [], group_count: 0, access: 'available' },
    sitemap_urls: [],
    discovered_url_count: 0,
    route_candidates: [],
    errors: [],
  };

  const sitemapQueue = [];
  try {
    const robots = await safeFetchText(result.robots_url, { target, timeoutMs, maxBytes: MAX_TEXT_BYTES, dnsCache });
    result.robots_status = robots.status;
    if (robots.status === 429 || robots.status >= 500) {
      result.robots_policy.access = 'blocked_temporarily';
      result.errors.push(`robots tijdelijk onbereikbaar: HTTP ${robots.status}`);
    } else if (robots.ok) {
      result.robots_policy = { ...parseRobotsPolicy(robots.text), access: 'available' };
      sitemapQueue.push(...parseRobotsSitemaps(robots.text, origin));
    } else {
      result.robots_policy.access = 'unavailable';
    }
  } catch (error) {
    result.robots_policy.access = 'unavailable';
    result.errors.push(`robots: ${String(error.message || error).slice(0, 180)}`);
  }

  for (const pathname of ['/sitemap.xml', '/sitemap_index.xml']) {
    const candidate = new URL(pathname, origin).toString();
    if (!sitemapQueue.includes(candidate)) sitemapQueue.push(candidate);
  }

  const pageUrls = new Set();
  const visitedSitemaps = new Set();
  while (sitemapQueue.length && visitedSitemaps.size < maxSitemaps && pageUrls.size < maxUrls) {
    const sitemapUrl = sitemapQueue.shift();
    if (!sitemapUrl || visitedSitemaps.has(sitemapUrl)) continue;
    if (!isSameOfficialSite(sitemapUrl, target) || !isAllowedByRobots(result.robots_policy, sitemapUrl) || isDangerousActionUrl(sitemapUrl)) continue;
    visitedSitemaps.add(sitemapUrl);
    try {
      const sitemap = await safeFetchText(sitemapUrl, { target, timeoutMs, maxBytes: MAX_TEXT_BYTES, dnsCache });
      if (!sitemap.ok) continue;
      result.sitemap_urls.push(sitemap.url);
      const locs = parseSitemapXml(sitemap.text);
      for (const loc of locs) {
        let parsed;
        try { parsed = new URL(loc); } catch { continue; }
        if (!isSameOfficialSite(parsed.toString(), target)) continue;
        if (/\.xml(?:$|\?)/i.test(parsed.pathname)) {
          if (!visitedSitemaps.has(parsed.toString()) && isAllowedByRobots(result.robots_policy, parsed.toString())) sitemapQueue.push(parsed.toString());
          continue;
        }
        if (!isAllowedByRobots(result.robots_policy, parsed.toString()) || isDangerousActionUrl(parsed.toString())) continue;
        if (pageUrls.size < maxUrls) pageUrls.add(parsed.toString());
      }
    } catch (error) {
      result.errors.push(`sitemap: ${String(error.message || error).slice(0, 180)}`);
    }
  }

  result.discovered_url_count = pageUrls.size;
  const priority = { contact_or_quote: 6, checkout: 5, cart: 5, booking: 4, main_service: 3, product_or_category: 3, other: 0 };
  result.route_candidates = [...pageUrls]
    .map((url) => ({ url, role_hint: classify(url), source: 'sitemap' }))
    .filter((item) => item.role_hint !== 'other')
    .sort((a, b) => priority[b.role_hint] - priority[a.role_hint])
    .slice(0, 30);
  return result;
}
