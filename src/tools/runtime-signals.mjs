const IGNORABLE_FAILURE = /(ERR_ABORTED|ERR_BLOCKED_BY_CLIENT|blockedbyclient)/i;

export function buildRequestFailureFinding({ target, pageUrl, requestUrl, resourceType = 'other', errorText = '', sameOfficialSite }) {
  if (!sameOfficialSite) return null;
  const failure = String(errorText || 'network failure').slice(0, 180);
  if (IGNORABLE_FAILURE.test(failure)) return null;
  return {
    severity: resourceType === 'document' ? 4 : 2,
    type: 'network_request_failed',
    url: pageUrl || target,
    detail: `${resourceType}: ${requestUrl} (${failure})`,
    route_category: 'runtime'
  };
}
