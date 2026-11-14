"""Private, offline read-only handoff of verified Leads candidates to Video.

No discovery, network, CRM, mail, or GitHub issue I/O. A caller supplies PRIVATE
candidate and evidence records. Output is a PRIVATE local JSON file, never logs.
An Approved record is not a marketing opt-in; mail permission is independent.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit

MAX_INPUT = 100
MAX_SELECTED = 5
VERIFIED = {'verified_with_detail', 'verified_activity_only',
            'verified_website_and_email'}
KINDS = {'seo', 'conversion', 'technical', 'webshop'}


def _safe_domain(url):
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if host.startswith('www.'):
            host = host[4:]
        if (parsed.scheme != 'https' or parsed.port not in (None, 443) or
            not host or parsed.username is not None or
                parsed.password or not host.count('.') or host == 'localhost'):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        if any(x in host for x in ('..', ' ', '\\', '/', '@')) or host.endswith(('.local', '.internal', '.test', '.invalid')):
            return None
        if not all(c.isalnum() or c in '.-' for c in host):
            return None
        return host
    except (TypeError, ValueError):
        return None


def _verified_observation(item, domain):
    if not isinstance(item, dict) or item.get('verified') is not True:
        return False
    if item.get('kind') not in KINDS or item.get('privacy_safe') is not True:
        return False
    if not all(isinstance(item.get(field), str) and item[field].strip()
               for field in ('source_url', 'observed_at', 'method', 'finding')):
        return False
    try:
        observed_date = datetime.fromisoformat(item['observed_at'].replace('Z', '+00:00')).date()
        if observed_date > datetime.now(timezone.utc).date():
            return False
    except (ValueError, TypeError):
        return False
    url_domain = _safe_domain(item['source_url'])
    return url_domain == domain or (url_domain and url_domain.endswith('.' + domain))


def shortlist(payload, limit=MAX_SELECTED):
    if type(limit) is not int or not 1 <= limit <= MAX_SELECTED:
        raise ValueError('invalid_limit')
    if not isinstance(payload, dict) or not isinstance(payload.get('candidates'), list):
        raise ValueError('invalid_input_shape')
    if len(payload['candidates']) > MAX_INPUT:
        raise ValueError('input_too_large')
    # A later suppression or unverified duplicate must never be bypassed by
    # an earlier valid record for the same website domain.
    blocked_domains = set()
    for record in payload['candidates']:
        if not isinstance(record, dict):
            continue
        name = _safe_domain(record.get('website'))
        if name and (record.get('historical_suppression_checked') is not True or
                     record.get('suppressed') is not False or
                     record.get('verification_status') not in VERIFIED or
                     record.get('local_business_fit') is not True):
            blocked_domains.add(name)
    considered = set()
    accepted = []
    counts = {'input': len(payload['candidates']), 'eligible': 0,
              'rejected': 0, 'selected': 0}
    for item in payload['candidates']:
        if not isinstance(item, dict):
            counts['rejected'] += 1
            continue
        domain = _safe_domain(item.get('website'))
        if not domain or domain in considered or domain in blocked_domains:
            counts['rejected'] += 1
            continue
        if (item.get('verification_status') not in VERIFIED or
            item.get('historical_suppression_checked') is not True or
            item.get('suppressed') is not False or
            item.get('local_business_fit') is not True or
            not isinstance(item.get('company'), str) or
            not item['company'].strip() or '@' in item['company']):
            counts['rejected'] += 1
            continue
        considered.add(domain)
        counts['eligible'] += 1
        raw = item.get('observations', [])
        observations = [o for o in raw if _verified_observation(o, domain)] if isinstance(raw, list) else []
        # Two independent findings may concern the same issue category.
        # Duplicated evidence cannot inflate the selection score.
        problems = {}
        for evidence in observations:
            if evidence.get('problem') is True:
                key = (evidence['kind'],
                       evidence['source_url'].split('?', 1)[0].rstrip('/').casefold(),
                       evidence['finding'].strip().casefold())
                problems.setdefault(key, evidence)
        unique = list(problems.values())
        issue_count = len(unique)
        issue_kinds = {e['kind'] for e in unique}
        screenshot_ready = sum(1 for e in unique if e.get('screenshot_ready') is True)
        quickfix = sum(1 for e in unique if isinstance(e.get('small_fix'), str)
                       and e['small_fix'].strip())
        score = (20 + (30 if issue_count >= 2 else 10 if issue_count else 0) +
                 (20 if screenshot_ready >= 2 else 10 if screenshot_ready else 0) +
                 (20 if quickfix >= 2 else 10 if quickfix else 0) +
                 (10 if len(observations) >= 2 else 0))
        ready = issue_count >= 2 and screenshot_ready >= 1 and quickfix >= 1 and score >= 60
        # Never transfer private contact fields, raw screenshots, or email values.
        accepted.append({
            'company': item['company'].strip()[:120],
            'website': 'https://' + urlsplit(item['website']).hostname.lower().rstrip('.') + '/',
            'status': 'READY_FOR_REVIEW' if ready else 'NEEDS_EVIDENCE',
            'video_priority_score': score,
            'verified_issue_categories': sorted(issue_kinds),
            'verified_problem_count': issue_count,
            'verified_observation_count': len(observations),
            'email_status': ('ELIGIBILITY_REVIEW_REQUIRED'
                             if item.get('marketing_permission') == 'confirmed'
                             else 'EMAIL_BLOCKED'),
            'evidence_review_required': True,
        })
    # Decision-ready leads always precede incomplete evidence, even at an equal score.
    accepted.sort(key=lambda x: (x['status'] != 'READY_FOR_REVIEW',
                                 -x['video_priority_score'], x['website']))
    selected = accepted[:limit]
    counts['selected'] = len(selected)
    counts['ready'] = sum(1 for item in selected if item['status'] == 'READY_FOR_REVIEW')
    return {'schema_version': '1.0', 'owner': 'video', 'status': 'REVIEW_ONLY',
            'counts': counts, 'selected': selected,
            'note': 'Not an email permission or confirmed website audit.'}


def _outside_repo(path):
    original = Path(path)
    if original.is_symlink():
        raise ValueError('symlink_output_forbidden')
    path = original.resolve()
    repo = Path(__file__).resolve().parents[1]
    if path == repo or repo in path.parents:
        raise ValueError('output_must_be_private_outside_repository')
    return path


def _write_private(path, data):
    path = _outside_repo(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.video-prep-', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='Private local evidence JSON')
    parser.add_argument('--output', required=True, help='Private local output JSON outside repository')
    parser.add_argument('--limit', type=int, default=5)
    args = parser.parse_args()
    try:
        with open(_outside_repo(args.input), encoding='utf-8') as f:
            payload = json.load(f)
        result = shortlist(payload, args.limit)
        _write_private(args.output, result)
    except (OSError, ValueError, json.JSONDecodeError):
        parser.error('Video handoff blocked: invalid private input/output or evidence. No changes made.')
    print('video_prep_private_handoff_ready')


if __name__ == '__main__':
    main()