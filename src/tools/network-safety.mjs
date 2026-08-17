import dns from 'node:dns/promises';
import net from 'node:net';
import { domainToASCII } from 'node:url';

export const USER_AGENT = 'Webactueel-Leadscanner/1.2.1 read-only';

const ACTION_PATH_RE = /(?:^|\/)(?:logout|log-out|signout|sign-out|unsubscribe|uitschrijven|delete(?:-account)?|remove-account|empty-cart|cart\/add|checkout\/confirm|order\/confirm|booking\/confirm|reservation\/confirm)(?:\/|$)/i;
const ACTION_QUERY_RE = /(?:^|[?&])(?:action=(?:logout|delete|remove|unsubscribe)|add-to-cart=|add_to_cart=|remove_item=|empty-cart=|wc-ajax=add_to_cart|confirm=(?:1|true)|submit=(?:1|true))(?:&|$)/i;

function ipv4Number(address) {
  const parts = address.split('.').map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) return null;
  return (((parts[0] * 256 + parts[1]) * 256 + parts[2]) * 256 + parts[3]) >>> 0;
}

function inV4Range(address, base, prefix) {
  const value = ipv4Number(address);
  const baseValue = ipv4Number(base);
  if (value === null || baseValue === null) return false;
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
  return (value & mask) === (baseValue & mask);
}

export function isPrivateOrReservedIp(address) {
  const type = net.isIP(address);
  if (type === 4) {
    const ranges = [
      ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
      ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24],
      ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24], ['203.0.113.0', 24],
      ['224.0.0.0', 4], ['240.0.0.0', 4],
    ];
    return ranges.some(([base, prefix]) => inV4Range(address, base, prefix));
  }
  if (type === 6) {
    const value = address.toLowerCase();
    if (value === '::' || value === '::1') return true;
    if (/^(fc|fd)/.test(value) || /^fe[89ab]/.test(value) || /^ff/.test(value) || /^2001:db8:/i.test(value)) return true;
    const mapped = value.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
    if (mapped) return isPrivateOrReservedIp(mapped[1]);
    return false;
  }
  return true;
}

export function normalizeHost(value) {
  const raw = value instanceof URL ? value.hostname : /^https?:\/\//i.test(String(value)) ? new URL(String(value)).hostname : String(value);
  const normalized = raw.trim().toLowerCase().replace(/\.$/, '');
  if (!normalized) throw new Error('Hostname ontbreekt.');
  if (net.isIP(normalized)) return normalized;
  const ascii = domainToASCII(normalized);
  if (!ascii) throw new Error(`Ongeldige hostname: ${normalized}`);
  return ascii.toLowerCase().replace(/\.$/, '');
}

export function canonicalSiteHost(value) {
  const host = normalizeHost(new URL(value));
  return host.startsWith('www.') ? host.slice(4) : host;
}

export function siteIdentity(value) {
  const parsed = new URL(value);
  const asciiHost = normalizeHost(parsed);
  return {
    hostname: asciiHost,
    canonical_host: asciiHost.startsWith('www.') ? asciiHost.slice(4) : asciiHost,
    origin: `${parsed.protocol}//${asciiHost}${parsed.port ? `:${parsed.port}` : ''}`,
    idn_normalized: parsed.hostname.toLowerCase().replace(/\.$/, '') !== asciiHost,
  };
}

export function isSameOfficialSite(candidate, target) {
  try {
    const candidateHost = normalizeHost(new URL(candidate));
    const root = canonicalSiteHost(target);
    return candidateHost === root || candidateHost === `www.${root}` || candidateHost.endsWith(`.${root}`);
  } catch {
    return false;
  }
}

export function isDangerousActionUrl(value) {
  try {
    const parsed = new URL(value);
    return ACTION_PATH_RE.test(parsed.pathname) || ACTION_QUERY_RE.test(`${parsed.search}&`);
  } catch {
    return true;
  }
}

export async function assertPublicUrl(value, { dnsCache = new Map() } = {}) {
  const parsed = new URL(value);
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Alleen publieke http/https-URLs zijn toegestaan.');
  if (parsed.username || parsed.password) throw new Error('URL-credentials zijn niet toegestaan.');
  const host = normalizeHost(parsed);
  if (!host) throw new Error('URL mist een hostname.');
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local')) throw new Error(`Niet-publieke hostname geblokkeerd: ${host}`);
  if (net.isIP(host)) {
    if (isPrivateOrReservedIp(host)) throw new Error(`Niet-publiek IP-adres geblokkeerd: ${host}`);
    return parsed;
  }
  let addresses = dnsCache.get(host);
  if (!addresses) {
    addresses = await dns.lookup(host, { all: true, verbatim: true });
    dnsCache.set(host, addresses);
  }
  if (!addresses.length) throw new Error(`Geen publiek DNS-resultaat voor ${host}.`);
  const blocked = addresses.find((entry) => isPrivateOrReservedIp(entry.address));
  if (blocked) throw new Error(`Hostname ${host} resolveert naar niet-publiek adres ${blocked.address}.`);
  return parsed;
}

export async function safeFetchText(value, {
  target = value,
  timeoutMs = 10000,
  maxBytes = 2_000_000,
  maxRedirects = 5,
  sameSiteRedirects = true,
  dnsCache = new Map(),
  method = 'GET',
} = {}) {
  let current = new URL(value).toString();
  for (let redirectCount = 0; redirectCount <= maxRedirects; redirectCount += 1) {
    await assertPublicUrl(current, { dnsCache });
    if (sameSiteRedirects && !isSameOfficialSite(current, target)) throw new Error(`Cross-site verzoek geblokkeerd: ${current}`);
    const response = await fetch(current, {
      method,
      redirect: 'manual',
      signal: AbortSignal.timeout(timeoutMs),
      headers: { 'user-agent': USER_AGENT },
    });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get('location');
      if (!location) return { ok: response.ok, status: response.status, url: current, text: '', headers: Object.fromEntries(response.headers.entries()) };
      if (redirectCount >= maxRedirects) throw new Error('Te veel redirects.');
      const next = new URL(location, current).toString();
      await assertPublicUrl(next, { dnsCache });
      if (sameSiteRedirects && !isSameOfficialSite(next, target)) throw new Error(`Cross-site redirect geblokkeerd: ${current} -> ${next}`);
      current = next;
      continue;
    }
    const text = method === 'HEAD' ? '' : (await response.text()).slice(0, maxBytes);
    return { ok: response.ok, status: response.status, url: current, text, headers: Object.fromEntries(response.headers.entries()) };
  }
  throw new Error('Redirectlus geblokkeerd.');
}

export function createRateLimiter(maxPerMinute = 120) {
  const limit = Math.max(1, Number(maxPerMinute) || 120);
  const starts = [];
  return {
    async take() {
      while (true) {
        const now = Date.now();
        while (starts.length && starts[0] <= now - 60000) starts.shift();
        if (starts.length < limit) {
          starts.push(now);
          return;
        }
        const delay = Math.max(25, starts[0] + 60000 - now);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    },
  };
}

export function createBoundaryState() {
  return {
    enforced: false,
    unsafe_continued: 0,
    blocked_non_read_requests: 0,
    blocked_action_requests: 0,
    blocked_private_network_requests: 0,
    blocked_cross_site_documents: 0,
    blocked_invalid_requests: 0,
    throttled_first_party_active_requests: 0,
    third_party_http_errors_ignored: 0,
  };
}

export function boundaryRespected(boundary) {
  return Boolean(boundary?.enforced) && Number(boundary?.unsafe_continued || 0) === 0;
}

export async function installPageSafety(page, {
  target,
  boundary,
  dnsCache = new Map(),
  activeLimiter = null,
} = {}) {
  if (!target || !boundary) throw new Error('installPageSafety vereist target en boundary.');
  boundary.enforced = true;
  await page.route('**/*', async (route) => {
    const request = route.request();
    const method = request.method().toUpperCase();
    const url = request.url();
    const resourceType = request.resourceType();
    try {
      if (!['GET', 'HEAD'].includes(method)) {
        boundary.blocked_non_read_requests += 1;
        await route.abort('blockedbyclient');
        return;
      }
      if (isDangerousActionUrl(url) && ['document', 'xhr', 'fetch'].includes(resourceType)) {
        boundary.blocked_action_requests += 1;
        await route.abort('blockedbyclient');
        return;
      }
      if (resourceType === 'document' && !isSameOfficialSite(url, target)) {
        boundary.blocked_cross_site_documents += 1;
        await route.abort('blockedbyclient');
        return;
      }
      await assertPublicUrl(url, { dnsCache });
      if (activeLimiter && isSameOfficialSite(url, target) && ['document', 'xhr', 'fetch'].includes(resourceType)) {
        boundary.throttled_first_party_active_requests += 1;
        await activeLimiter.take();
      }
      await route.continue();
    } catch {
      boundary.blocked_private_network_requests += 1;
      await route.abort('blockedbyclient').catch(() => {});
    }
  });
}