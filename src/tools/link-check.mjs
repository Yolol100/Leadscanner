import { LinkChecker } from 'linkinator';

export async function checkRouteLinks(target, routePlan = []) {
  const origin = new URL(target).origin;
  const paths = [...new Set((routePlan || []).map((item) => item?.url).filter(Boolean))].slice(0, 4);
  if (!paths.length) paths.push(target);
  try {
    const checker = new LinkChecker();
    const result = await checker.check({
      path: paths,
      recurse: false,
      concurrency: 4,
      timeout: 10000,
      retry: false,
      linksToSkip: async (url) => {
        try { return new URL(url).origin !== origin; } catch { return true; }
      },
    });
    const links = Array.isArray(result.links) ? result.links : [];
    const broken = links
      .filter((item) => item.state === 'BROKEN' && ![401, 403, 429, 999].includes(Number(item.status)))
      .map((item) => ({ url: item.url, parent: item.parent || null, status: item.status || null, state: item.state }))
      .slice(0, 25);
    const skipped = links.filter((item) => item.state === 'SKIPPED').length;
    return { source: 'linkinator', checked: links.length, passed: broken.length === 0, broken, skipped };
  } catch (error) {
    return { source: 'linkinator', checked: 0, passed: null, broken: [], skipped: 0, error: String(error.message || error).slice(0, 220) };
  }
}
