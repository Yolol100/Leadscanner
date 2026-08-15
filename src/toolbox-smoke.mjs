import http from 'node:http';
import { once } from 'node:events';
import { parseSitemapXml, parseRobotsSitemaps } from './tools/discovery.mjs';
import { detectTechnologyFromHtml } from './tools/tech-detect.mjs';
import { checkRouteLinks } from './tools/link-check.mjs';
import { checkDutchText } from './tools/language-check.mjs';

const sitemap = parseSitemapXml('<urlset><url><loc>https://example.test/diensten/</loc></url></urlset>');
if (sitemap[0] !== 'https://example.test/diensten/') throw new Error('Sitemap parser failed');
const robots = parseRobotsSitemaps('Sitemap: https://example.test/sitemap.xml', 'https://example.test');
if (robots[0] !== 'https://example.test/sitemap.xml') throw new Error('Robots parser failed');
const tech = detectTechnologyFromHtml('<link href="/wp-content/plugins/elementor/assets/a.css"><div class="woocommerce"></div>');
if (!['WordPress', 'Elementor', 'WooCommerce'].every((name) => tech.some((item) => item.name === name))) throw new Error('Tech detection failed');

const server = http.createServer((req, res) => {
  if (req.url === '/') { res.writeHead(200, { 'content-type': 'text/html' }); res.end('<a href="/missing">missing</a>'); return; }
  res.writeHead(404, { 'content-type': 'text/plain' }); res.end('not found');
});
server.listen(0, '127.0.0.1');
await once(server, 'listening');
try {
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}/`;
  const linkResult = await checkRouteLinks(base, [{ url: base, role: 'home' }]);
  if (!linkResult.broken.some((item) => Number(item.status) === 404)) throw new Error('Linkinator integration failed');
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
