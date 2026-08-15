const DETECTORS = [
  ['WordPress', /wp-content\/|wp-includes\/|generator[^>]+wordpress/i, 'high'],
  ['Elementor', /elementor(?:-frontend|-pro)?|elementor-widget|data-elementor-/i, 'high'],
  ['WooCommerce', /woocommerce|wc-block|wc-ajax|woocommerce-layout/i, 'high'],
  ['Shopify', /cdn\.shopify\.com|shopify-section|Shopify\.theme/i, 'high'],
  ['Wix', /wixstatic\.com|wix-thunderbolt|X-Wix-/i, 'high'],
  ['Webflow', /data-wf-page|data-wf-site|webflow\.css/i, 'high'],
  ['Squarespace', /static1\.squarespace\.com|squarespace-cdn|squarespace\.com\/universal/i, 'high'],
  ['Drupal', /drupalSettings|sites\/default\/files|generator[^>]+drupal/i, 'medium'],
  ['Joomla', /generator[^>]+joomla|\/media\/system\/js\//i, 'medium'],
];

export function detectTechnologyFromHtml(html, headers = {}) {
  const headerText = Object.entries(headers).map(([key, value]) => `${key}:${value}`).join('\n');
  const haystack = `${String(html).slice(0, 1_500_000)}\n${headerText}`;
  return DETECTORS
    .filter(([, pattern]) => pattern.test(haystack))
    .map(([name, , confidence]) => ({ name, confidence }));
}

export async function detectTechnology(target) {
  try {
    const response = await fetch(target, {
      redirect: 'follow',
      signal: AbortSignal.timeout(12000),
      headers: { 'user-agent': 'Webactueel-Leadscanner/1.2 read-only' },
    });
    const html = await response.text();
    const headers = Object.fromEntries(response.headers.entries());
    return {
      source: 'html-signatures',
      url: response.url,
      status: response.status,
      detected: detectTechnologyFromHtml(html, headers),
    };
  } catch (error) {
    return { source: 'html-signatures', detected: [], error: String(error.message || error).slice(0, 220) };
  }
}
