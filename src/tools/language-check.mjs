export async function checkDutchText(text, endpoint = process.env.LANGUAGE_TOOL_URL || 'http://127.0.0.1:8010/v2/check') {
  const clean = String(text || '').replace(/\s+/g, ' ').trim().slice(0, 10000);
  if (clean.length < 80) return { source: 'languagetool-local', checked_chars: clean.length, matches: [] };
  try {
    const body = new URLSearchParams({ language: 'nl', text: clean });
    const response = await fetch(endpoint, {
      method: 'POST',
      body,
      signal: AbortSignal.timeout(20000),
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const matches = (data.matches || []).slice(0, 25).map((match) => ({
      message: match.message,
      short_message: match.shortMessage || '',
      offset: match.offset,
      length: match.length,
      rule_id: match.rule?.id || null,
      category: match.rule?.category?.id || null,
      replacements: (match.replacements || []).slice(0, 3).map((item) => item.value),
      context: match.context?.text || null,
    }));
    return { source: 'languagetool-local', checked_chars: clean.length, matches };
  } catch (error) {
    return { source: 'languagetool-local', checked_chars: clean.length, matches: [], error: String(error.message || error).slice(0, 220) };
  }
}
