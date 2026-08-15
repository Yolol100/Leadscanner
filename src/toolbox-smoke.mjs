import http from 'node:http';
import { once } from 'node:events';
import { parseSitemapXml, parseRobotsPolicy, parseRobotsSitemaps, isAllowedByRobots } from './tools/discovery.mjs';
import { buildRoute, routeCoverage } from './tools/route-planner.mjs';
import { assertPublicUrl, isDangerousActionUrl, isPrivateOrReservedIp, isSameOfficialSite } from './tools/network-safety.mjs';
import { detectTechnologyFromHtml } from './tools/tech-detect.mjs';
import { checkRouteLinks } from './tools/link-check.mjs';
import { checkDutchText } from './tools/language-check.mjs';

const sitemap = parseSitemapXml('<urlset><url><loc>https://example.test/diensten/</loc></url></urlset>');
if (sitemap[0] !== 'https://example.test/diensten/') throw new Error('Sitemap parser failed');
const sitemaps = parseRobotsSitemaps('Sitemap: https://example.test/sitemap.xml', 'https://example.test');
if (sitemaps[0] !== 'https://example.test/sitemap.xml') throw new Error('Robots sitemap parser failed');
const policy = { ...parseRobotsPolicy('User-agent: *\nDisallow: /prive/\nAllow: /prive/openbaar/'), access: 'available' };
if (isAllowedByRobots(policy, 'https://example.test/prive/geheim')) throw new Error('Robots disallow failed');
if (!isAllowedByRobots(policy, 'https://example.test/prive/openbaar/pagina')) throw new Error('Robots allow precedence failed');
if (!isPrivateOrReservedIp('127.0.0.1') || !isPrivateOrReservedIp('169.254.169.254') || isPrivateOrReservedIp('8.8.8.8')) throw new Error('IP safety classification failed');
if (!isDangerousActionUrl('https://example.test/cart/add?id=1') || isDangerousActionUrl('https://example.test/checkout/')) throw new Error('Action URL guard failed');
if (!isSameOfficialSite('https://www.example.test/a', 'https://example.test/') || isSameOfficialSite('https://evil.test/', 'https://example.test/')) throw new Error('Official-site redirect guard failed');
let privateBlocked = false;
try { await assertPublicUrl('http://127.0.0.1/'); } catch { privateBlocked = true; }
if (!privateBlocked) throw new Error('Private target should be blocked');

const discoveryFixture = {
  robots_policy: policy,
  route_candidates: [
    { url: 'https://example.test/diensten/dakwerk', role_hint: 'main_service', source: 'sitemap' },
    { url: 'https://example.test/contact', role_hint: 'contact_or_quote', source: 'sitemap' },
  ],
};
const planned = buildRoute({ homeUrl: 'https://example.test/', links: [], discovery: discoveryFixture, siteTypeHint: 'service', maxPages: 4 });
if (planned.siteType !== 'service' || planned.pages.length < 3 || planned.pages[1].role !== 'main_service') throw new Error('Sitemap-assisted route planner failed');
const coverage = routeCoverage(planned.pages, planned.pages.flatMap((page) => [
  { device: 'desktop', route_category: page.role, planned_url: page.url },
  { device: 'mobile', route_category: page.role, planned_url: page.url },
]), 'desktop');
if (!coverage.complete) throw new Error('Exact route coverage failed');
const incomplete = routeCoverage(planned.pages, [{ device: 'desktop', route_category: 'home', planned_url: planned.pages[0].url }], 'desktop');
if (incomplete.complete) throw new Error('Incomplete route must not pass exact coverage');

const tech = detectTechnologyFromHtml('<link href="/wp-content/plugins/elementor/assets/a.css"><div class="woocommerce"></div>');
if (!['WordPress', 'Elementor', 'WooCommerce'].every((name) => tech.some((item) => item.name === name))) throw new Error('Tech detection failed');

const server = http.createServer((req, res) => {
  if (req.url === '/') { res.writeHead(200, { 'content-type': 'text/html' }); res.end('<a href="/missing">missing</a><a href="/logout">logout</a>'); return; }
  if (req.url === '/logout') { res.writeHead(200, { 'content-type': 'text/plain' }); res.end('should be skipped'); return; }
  res.writeHead(404, { 'content-type': 'text/plain' }); res.end('not found');
});
server.listen(0, '127.0.0.1');
await once(server, 'listening');
try {
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}/`;
  const linkResult = await checkRouteLinks(base, [{ url: base, role: 'home' }], { allowPrivateForTest: true });
  if (!linkResult.broken.some((item) => Number(item.status) === 404)) throw new Error('Linkinator integration failed');
  if (linkResult.broken.some((item) => /logout/i.test(item.url || ''))) throw new Error('Risky action URL should be skipped by link checker');
} finally {
  server.close();
  await once(server, 'close');
}

if (String(process.env.RUN_LANGUAGE_TOOL || 'false').toLowerCase() === 'true') {
  const language = await checkDutchText('Dit is een eenvoudige Nederlandse testzin. Deze tweede zin zorgt dat er genoeg tekst is voor de controle door LanguageTool.');
  if (language.error) throw new Error(`LanguageTool integration failed: ${language.error}`);
  if (!Array.isArray(language.matches)) throw new Error('LanguageTool returned invalid result');
}

console.log('Toolbox smoke OK');
