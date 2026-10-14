import unittest
from unittest.mock import Mock, patch
import registry_readonly as reg


class RegistryTests(unittest.TestCase):
    def test_read_only(self):
        session = Mock()
        response = Mock(status_code=200)
        response.json.return_value = {"values": [["a"], ["b"]]}
        session.get.return_value = response
        self.assertEqual(len(reg.read_values(session, reg.REGISTRY_ID, reg.REGISTRY_TAB)), 2)
        session.post.assert_not_called()
        session.delete.assert_not_called()

    def test_historical_suppression_required(self):
        with patch.object(reg, "read_values", return_value=[["dummy"]]),              patch.object(reg, "load_registry_values", return_value=[{"identity": {}}]),              patch.object(reg, "read_production_state",
                          return_value={"status": "missing"}):
            with self.assertRaisesRegex(RuntimeError, "historical_suppression_unavailable"):
                reg.load_suppressions(Mock())
