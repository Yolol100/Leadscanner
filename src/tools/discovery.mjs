const DEFAULT_TIMEOUT_MS = 10000;
const MAX_TEXT_BYTES = 2_000_000;

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
  for (const line of String(text).split(/\r?\n/)) {
    const match = line.match(/^\s*sitemap\s*:\s*(\S+)\s*$/i);
    if (!match) continue;
    try { values.push(new URL(match[1], origin).toString()); } catch {}
  }
  return [...new Set(values)];
}

async function fetchText(url, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const response = await fetch(url, {
    redirect: 'follow',
    signal: AbortSignal.timeout(timeoutMs),
    headers: { 'user-agent': 'Webactueel-Leadscanner/1.2 read-only' },
  });
  const text = (await response.text()).slice(0, MAX_TEXT_BYTES);
  return { ok: response.ok, status: response.status, url: response.url, text };
}

function classify(url) {
  const value = new URL(url).pathname.toLowerCase();
  if (/(contact|offerte|aanvraag|prijsopgave)/.test(value)) return 'contact_or_quote';
  if (/(checkout|afrekenen)/.test(value)) return 'checkout';
  if (/(winkelwagen|\/cart(?:\/|$))/.test(value)) return 'cart';
  if (/(boek|booking|afspraak|reserver)/.test(value)) return 'booking';
  if (/(product|shop|winkel|categorie|category)/.test(value)) return 'product_or_category';
  if (/(dienst|service|werkzaam|schilder|dak|tuin|install|loodgiet|elektra|verwarm|airco|renov)/.test(value)) return 'main_service';
  return 'other';
}

export async function discoverSite(target, { maxSitemaps = 4, maxUrls = 300 } = {}) {
  const origin = new URL(target).origin;
  const result = {
    source: 'robots+sitemap',
    robots_url: new URL('/robots.txt', origin).toString(),
    robots_status: null,
    sitemap_urls: [],
    discovered_url_count: 0,
    route_candidates: [],
    errors: [],
  };

  const sitemapQueue = [];
  try {
    const robots = await fetchText(result.robots_url);
    result.robots_status = robots.status;
    sitemapQueue.push(...parseRobotsSitemaps(robots.text, origin));
  } catch (error) {
    result.errors.push(`robots: ${String(error.message || error).slice(0, 180)}`);
  }

  for (const path of ['/sitemap.xml', '/sitemap_index.xml']) {
    const candidate = new URL(path, origin).toString();
    if (!sitemapQueue.includes(candidate)) sitemapQueue.push(candidate);
  }

  const pageUrls = new Set();
  const visitedSitemaps = new Set();
  while (sitemapQueue.length && visitedSitemaps.size < maxSitemaps && pageUrls.size < maxUrls) {
    const sitemapUrl = sitemapQueue.shift();
    if (!sitemapUrl || visitedSitemaps.has(sitemapUrl)) continue;
    visitedSitemaps.add(sitemapUrl);
    try {
      const sitemap = await fetchText(sitemapUrl);
      if (!sitemap.ok) continue;
      result.sitemap_urls.push(sitemap.url);
      const locs = parseSitemapXml(sitemap.text);
      for (const loc of locs) {
        let parsed;
        try { parsed = new URL(loc); } catch { continue; }
        if (parsed.origin !== origin) continue;
        if (/\.xml(?:$|\?)/i.test(parsed.pathname)) {
          if (!visitedSitemaps.has(parsed.toString())) sitemapQueue.push(parsed.toString());
          continue;
        }
        if (pageUrls.size < maxUrls) pageUrls.add(parsed.toString());
      }
    } catch (error) {
      result.errors.push(`sitemap: ${String(error.message || error).slice(0, 180)}`);
    }
  }

  result.discovered_url_count = pageUrls.size;
  const priority = { contact_or_quote: 6, checkout: 5, cart: 5, booking: 4, main_service: 3, product_or_category: 3, other: 0 };
  result.route_candidates = [...pageUrls]
    .map((url) => ({ url, role_hint: classify(url) }))
    .filter((item) => item.role_hint !== 'other')
    .sort((a, b) => priority[b.role_hint] - priority[a.role_hint])
    .slice(0, 30);
  return result;
}
