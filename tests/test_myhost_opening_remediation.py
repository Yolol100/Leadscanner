import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import myhost_opening_remediation as repair


class OpeningRemediationTests(unittest.TestCase):
    def request(self, mode='audit'):
        return {'mode': mode, 'source_archive_artifact_id': 1, 'source_artifact_ids': [2], 'offset': 0, 'limit': 1, **({'audit_artifact_id': 3} if mode != 'audit' else {})}

    def test_read_only_audit_never_appends_or_removes(self):
        row = {'lead_id': 'growth-'+'a'*20, 'email': 'info@example.nl', 'company': 'Voorbeeld'}
        current = {'lead_id': row['lead_id'], 'actual_lead_id': row['lead_id'], 'count': 1, 'duplicate': False, 'to': row['email'], 'subject': 'Idee voor Voorbeeld', 'body': 'Hallo,\n\nEen fout metadatafragment.\n\nAanbod', 'review_status': 'contact-basis'}
        with patch.object(repair, 'source_selection', return_value=[row]), patch.object(repair, 'website_audit', return_value={'status': 'hold', 'reason': 'HTTP 403', 'pages': []}), patch.object(repair, 'connect_imap', return_value=MagicMock()), patch.object(repair, 'find_drafts_folder', return_value='Drafts'), patch.object(repair, 'read_current', return_value=current), patch.object(repair, 'append_and_verify') as append, patch.object(repair, 'remove_hold_draft') as remove:
            result = repair.run(self.request(), Path('.'))
            self.assertEqual(result['hold_count'], 1)
            self.assertEqual(result['items'][0]['before']['body'], current['body'])
            self.assertTrue(result['read_only'])
            append.assert_not_called(); remove.assert_not_called()

    def test_absent_draft_is_not_recreated(self):
        row = {'lead_id': 'growth-'+'a'*20, 'email': 'info@example.nl'}
        absent = {'lead_id': row['lead_id'], 'count': 0, 'duplicate': False}
        audit = {'lead_ids': [row['lead_id']], 'source_artifact_ids': [2], 'items': [{'lead_id': row['lead_id'], 'before': absent, 'website': {'status': 'hold'}}]}
        with patch.object(repair, 'source_selection', return_value=[row]), patch.object(repair, 'website_audit', return_value={'status': 'hold', 'reason': 'unavailable'}), patch.object(repair, 'connect_imap', return_value=MagicMock()), patch.object(repair, 'find_drafts_folder', return_value='Drafts'), patch.object(repair, 'read_current', return_value=absent), patch.object(repair, 'append_and_verify') as append, patch.object(repair, 'remove_hold_draft') as remove:
            result = repair.run({**self.request('apply'), 'holds': {row['lead_id']: 'unavailable official website'}}, Path('.'), audit)
            self.assertEqual(result['absent_count'], 1)
            append.assert_not_called(); remove.assert_not_called()

    def test_stale_full_body_blocks_write_even_when_identity_matches(self):
        row = {'lead_id': 'growth-'+'a'*20, 'email': 'info@example.nl'}
        before = {'lead_id': row['lead_id'], 'count': 1, 'body': 'old'}
        audit = {'lead_ids': [row['lead_id']], 'source_artifact_ids': [2], 'items': [{'lead_id': row['lead_id'], 'before': before}]}
        with patch.object(repair, 'source_selection', return_value=[row]), patch.object(repair, 'connect_imap', return_value=MagicMock()), patch.object(repair, 'find_drafts_folder', return_value='Drafts'), patch.object(repair, 'read_current', return_value={**before, 'body': 'changed'}), patch.object(repair, 'append_and_verify') as append, patch.object(repair, 'remove_hold_draft') as remove:
            result = repair.run({**self.request('apply'), 'holds': {row['lead_id']: 'official proof unavailable'}}, Path('.'), audit)
            self.assertEqual(result['hold_count'], 1)
            self.assertEqual(len(result['blockers']), 1)
            append.assert_not_called(); remove.assert_not_called()
