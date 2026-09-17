const DISCOVERY_ONLY = new Set(['active_ads', 'inactive_social']);

export function classifyProspectSignal(signal = {}) {
  const type = String(signal.type || '').trim().toLowerCase();

  if (type === 'website_absent') {
    const pass = Boolean(
      signal.officialBusinessProfile &&
      signal.websiteLinkAbsent === true &&
      signal.publicBusinessEmailVerified === true
    );
    return pass
      ? { decision: 'qualify', offer: 'website_webshop_improvement', evidenceClass: 'official_business_profile' }
      : { decision: 'skip', offer: null, evidenceClass: 'insufficient' };
  }

  if (DISCOVERY_ONLY.has(type)) {
    return { decision: 'prioritize_discovery', offer: null, evidenceClass: 'discovery_only' };
  }

  if (type === 'missing_llms_txt' || type === 'broken_llms_txt') {
    return { decision: 'not_search_evidence', offer: null, evidenceClass: 'non_qualifying' };
  }

  return { decision: 'review', offer: null, evidenceClass: 'unknown' };
}

export function canClaimPreparedArtifact({ exists, readbackVerified } = {}) {
  return exists === true && readbackVerified === true;
}
