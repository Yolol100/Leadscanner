"""Deterministic no-network regression tests for the optional Video handoff."""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import video_candidate_handoff as video


def observation(kind, problem=True, **kw):
    entry = dict(kind=kind, source_url='https://voorbeeld.nl/diensten',
                 verified=True, privacy_safe=True, observed_at='2026-11-14',
                 method='human-review', finding='Visible issue', problem=problem,
                 screenshot_ready=True, small_fix='Improve CTA')
    entry.update(kw)
    return entry


def candidate(**kw):
    entry = dict(company='Test Hovenier', website='https://voorbeeld.nl/',
                 verification_status='verified_with_detail',
                 historical_suppression_checked=True, suppressed=False,
                 local_business_fit=True,
                 observations=[observation('conversion'), observation('technical')],
                 email='info@voorbeeld.nl', marketing_permission='not_confirmed')
    entry.update(kw)
    return entry


class VideoCandidateHandoffTests(unittest.TestCase):
    def test_two_verified_categories_ready_but_email_blocked(self):
        data = video.shortlist({'candidates': [candidate()]})
        self.assertEqual(data['selected'][0]['status'], 'READY_FOR_REVIEW')
        self.assertEqual(data['selected'][0]['email_status'], 'EMAIL_BLOCKED')
        self.assertNotIn('\"email\":', json.dumps(data))
        self.assertNotIn('info@', json.dumps(data))

    def test_suppressed_and_unknown_suppression_fail_closed(self):
        for val in (True, None, 'false'):
            self.assertEqual(video.shortlist({'candidates': [candidate(suppressed=val)]})['selected'], [])
        self.assertEqual(video.shortlist({'candidates': [candidate(historical_suppression_checked=False)]})['selected'], [])

    def test_unverified_and_no_fit_rejected(self):
        for args in ({'verification_status': 'hint'}, {'local_business_fit': False}):
            self.assertEqual(video.shortlist({'candidates': [candidate(**args)]})['selected'], [])

    def test_email_permission_separate_from_approval(self):
        selected = video.shortlist({'candidates': [candidate(marketing_permission='confirmed')]})['selected'][0]
        self.assertEqual(selected['email_status'], 'ELIGIBILITY_REVIEW_REQUIRED')

    def test_not_reproduce_problem_unless_two_categories(self):
        entry = candidate(observations=[observation('conversion'), observation('conversion')])
        self.assertEqual(video.shortlist({'candidates': [entry]})['selected'][0]['status'], 'NEEDS_EVIDENCE')

    def test_unknown_and_unsafe_findings_not_counted(self):
        entry = candidate(observations=[observation('conversion', verified=False), observation('technical')])
        r = video.shortlist({'candidates': [entry]})['selected'][0]
        self.assertEqual(r['verified_observation_count'], 1)
        self.assertEqual(r['status'], 'NEEDS_EVIDENCE')

    def test_no_cross_domain_pseudo_evidence(self):
        entry = candidate(observations=[observation('conversion'), observation('technical', source_url='https://attacker.example')])
        self.assertEqual(video.shortlist({'candidates': [entry]})['selected'][0]['status'], 'NEEDS_EVIDENCE')

    def test_bad_domains_and_local_private_hosts_denied(self):
        for site in ('http://voorbeeld.nl', 'https://localhost', 'https://127.0.0.1/', 'https://a',
                     'https://user:secret@voorbeeld.nl', 'file:///etc/passwd'):
            self.assertEqual(video.shortlist({'candidates': [candidate(website=site)]})['selected'], [])

    def test_deduplicate_and_limit(self):
        data = video.shortlist({'candidates': [candidate(), candidate(company='duplicate')]})
        self.assertEqual(data['counts']['selected'], 1)
        with self.assertRaises(ValueError):video.shortlist({'candidates': [candidate()]}, 6)

    def test_limit_rejects_boolean_and_excessive_input(self):
        with self.assertRaises(ValueError):video.shortlist({'candidates':[candidate()]}, True)
        with self.assertRaises(ValueError):video.shortlist({'candidates':[{}]*101})

    def test_output_private_atomic_and_not_in_repo(self):
        data = video.shortlist({'candidates': [candidate()]})
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'video.json'
            video._write_private(target, data)
            self.assertEqual(json.loads(target.read_text())['owner'],'video')
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
        with self.assertRaises(ValueError):video._outside_repo(Path(__file__).resolve().parents[1]/'leads-private.json')

    def test_url_query_does_not_leak_recipient_data(self):
        r = video.shortlist({'candidates': [candidate(website='https://voorbeeld.nl/?email=secret%40ex.nl&token=secret')]})
        self.assertEqual(r['selected'][0]['website'], 'https://voorbeeld.nl/')
        self.assertNotIn('secret', json.dumps(r))

    def test_local_and_invalid_tlds_blocked(self):
        for site in ('https://thing.local', 'https://metadata.internal', 'https://example.test'):
            self.assertEqual(video.shortlist({'candidates': [candidate(website=site)]})['selected'], [])

    def test_company_email_disguised_as_name_is_blocked(self):
        self.assertEqual(video.shortlist({'candidates': [candidate(company='sales@voorbeeld.nl')]})['selected'], [])

    def test_input_shape_invalid(self):
        for payload in (None, [], {}, {'candidates': 'not-list'}):
            with self.assertRaises(ValueError):video.shortlist(payload)

    def test_output_symlink_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'target.json'
            target.write_text('{}')
            linked = Path(tmp) / 'alias.json'
            linked.symlink_to(target)
            with self.assertRaises(ValueError):video._outside_repo(linked)

    def test_no_network_or_send_dependencies(self):
        source=Path(video.__file__).read_text()
        for forbidden in ('import requests','smtplib','imaplib','create_draft','send_message'):
            self.assertNotIn(forbidden,source)

if __name__=='__main__': unittest.main()