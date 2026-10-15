"""Prove that both private history and private draft queue suppress rediscovery.

All identities below are fictional. No external requests, mailbox access or sending.
"""
import unittest
from unittest.mock import Mock, patch

from dedupe_preflight import match_candidate
from registry_readonly import (
    DRAFT_QUEUE_HEADERS, LEAD_HISTORY_HEADERS, load_discovery_suppressions,
)


class PermanentLeadMemoryTests(unittest.TestCase):
    HISTORY = [
        "38713314097", "Fictief Hovenier", "https://hovenier-fictief.nl/",
        "info@hovenier-fictief.nl", "https://hovenier-fictief.nl/contact",
        "verified_lead", "", "2026-10-15T09:36:39Z",
    ]
    DRAFT = [
        "draft-" + "a" * 32, "2026-10-15", "Fictieve Bakker",
        "info@bakker-fictief.nl", "https://bakker-fictief.nl/contact",
        "Fictieve onderwerpregel", "Fictieve mail",
    ]

    def make_loader(self, *, history=None, queue=None):
        history = [LEAD_HISTORY_HEADERS, self.HISTORY] if history is None else history
        queue = [DRAFT_QUEUE_HEADERS, self.DRAFT] if queue is None else queue
        session = Mock()

        def read(_session, _spreadsheet_id, tab):
            return history if tab == "LeadHistory" else queue

        return session, read

    def test_known_found_company_and_existing_draft_are_both_excluded(self):
        session, read = self.make_loader()
        with patch("registry_readonly.load_suppressions", return_value=[]) as hmac, \
             patch("registry_readonly.read_values", side_effect=read) as reads:
            registry = load_discovery_suppressions(session)
        hmac.assert_called_once_with(session=session)
        self.assertEqual(reads.call_count, 2)
        # A different name with the same site must still be excluded.
        self.assertIsNotNone(match_candidate({
            "name_hint": "Andere bedrijfsnaam", "website_hint": "https://hovenier-fictief.nl/"
        }, registry))
        self.assertIsNotNone(match_candidate({
            "name_hint": "Andere bakker", "website_hint": "https://bakker-fictief.nl/"
        }, registry))
        self.assertIsNotNone(match_candidate({
            "name_hint": "Fictieve Bakker", "website_hint": "https://andere-fictieve-zaak.nl/"
        }, registry))
        self.assertIsNone(match_candidate({
            "name_hint": "Echt Nieuw Fictief Bedrijf",
            "website_hint": "https://unieke-fictieve-zaak.nl/"
        }, registry))

    def test_corrupt_history_or_queue_blocks_discovery(self):
        cases = (
            ([["wrong header"], self.HISTORY], None),
            (None, [["wrong header"], self.DRAFT]),
            ([LEAD_HISTORY_HEADERS, self.HISTORY, self.HISTORY], None),
            (None, [DRAFT_QUEUE_HEADERS, self.DRAFT, self.DRAFT]),
            ([LEAD_HISTORY_HEADERS, []], None),
        )
        for history, queue in cases:
            with self.subTest(history=history is not None, queue=queue is not None):
                session, reader = self.make_loader(history=history, queue=queue)
                with patch("registry_readonly.load_suppressions", return_value=[]), \
                     patch("registry_readonly.read_values", side_effect=reader):
                    with self.assertRaises(RuntimeError):
                        load_discovery_suppressions(session)

    def test_draft_history_does_not_block_first_draft_creation(self):
        # Discovery suppression includes all saved drafts, but the canonical
        # mail-creation registry is historically suppressed only.
        import myhost_draft
        self.assertIs(myhost_draft.load_suppressions.__module__, "registry_readonly")


if __name__ == "__main__":
    unittest.main()
