import fs from 'node:fs/promises';
import path from 'node:path';
import { discoverSite } from './tools/discovery.mjs';
import { detectTechnology } from './tools/tech-detect.mjs';
import { checkRouteLinks } from './tools/link-check.mjs';
import { checkDutchText } from './tools/language-check.mjs';

const OUT = path.resolve('scan-results');
const flag = (name, fallback) => String(process.env[name] ?? fallback).toLowerCase() === 'true';
const runDiscovery = flag('RUN_DISCOVERY', true);
const runTechDetect = flag('RUN_TECH_DETECT', true);
const runLinkinator = flag('RUN_LINKINATOR', true);
const runLanguageTool = flag('RUN_LANGUAGE_TOOL', false);

const safe = (value) => value.replace(/^https?:\/\//, '').replace(/[^a-z0-9.-]+/gi, '_').replace(/_+/g, '_').slice(0, 100);

function visibleDutchText(site) {
  const desktop = (site.profiles || []).find((profile) => profile.profile === 'desktop');
  return (desktop?.pages || [])
    .map((page) => page.text_sample || '')
    .filter(Boolean)
    .join('\n')
    .slice(0, 10000);
}

async function persistSite(site) {
  const dir = path.join(OUT, safe(site.target));
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, 'result.json'), JSON.stringify(site, null, 2));
}

const resultsPath = path.join(OUT, 'results.json');
const results = JSON.parse(await fs.readFile(resultsPath, 'utf8'));

for (const site of results) {
  const supplemental = { ...(site.supplemental || {}), scoring_policy: 'supplemental_only_no_automatic_lead_score' };
  const tasks = [];
  if (runDiscovery) tasks.push(discoverSite(site.target).then((value) => ['discovery', value]));
  if (runTechDetect) tasks.push(detectTechnology(site.target).then((value) => ['technology', value]));
  if (runLinkinator) tasks.push(checkRouteLinks(site.target, site.route_plan || []).then((value) => ['linkinator', value]));
  if (runLanguageTool) tasks.push(checkDutchText(visibleDutchText(site)).then((value) => ['language', value]));
  Object.assign(supplemental, Object.fromEntries(await Promise.all(tasks)));
  site.supplemental = supplemental;
  await persistSite(site);
}

await fs.writeFile(resultsPath, JSON.stringify(results, null, 2));

const summaryPath = path.join(OUT, 'summary.md');
let summary = '';
try { summary = await fs.readFile(summaryPath, 'utf8'); } catch {}
const extra = ['', '# Aanvullende toolbox-signalen', '', 'Deze signalen zijn supplementair en wijzigen de Leadscore niet automatisch.', ''];
for (const site of results) {
  const s = site.supplemental || {};
  extra.push(`## ${site.target}`);
  if (s.discovery) extra.push(`- Sitemap/robots: ${s.discovery.discovered_url_count || 0} URL(s), ${s.discovery.route_candidates?.length || 0} routekandidaat/kandidaten.`);
  if (s.technology) extra.push(`- Tech-detect: ${s.technology.detected?.map((item) => item.name).join(', ') || 'geen duidelijke technologie-signatuur'}.`);
  if (s.linkinator) extra.push(`- Linkinator: ${s.linkinator.checked || 0} link(s) gecontroleerd, ${s.linkinator.broken?.length || 0} bruikbare kapotte link(s).`);
  if (s.language) extra.push(`- LanguageTool: ${s.language.matches?.length || 0} taalsignaal/signalen op ${s.language.checked_chars || 0} tekens.`);
  extra.push('');
}
await fs.writeFile(summaryPath, `${summary.trim()}\n${extra.join('\n')}\n`);
console.log(`Aanvullende checks verwerkt voor ${results.length} website(s).`);
