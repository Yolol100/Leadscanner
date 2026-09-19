import unittest

from runtime_branch import parse_runtime_branch


class RuntimeBranchTests(unittest.TestCase):
    def test_valid_runtime_branch(self):
        self.assertEqual(
            parse_runtime_branch("runtime/myhost-draft/lead-1"),
            "lead-1",
        )

    def test_prefix_is_required(self):
        with self.assertRaises(ValueError):
            parse_runtime_branch("feature/lead-1")

    def test_empty_id_blocks(self):
        with self.assertRaises(ValueError):
            parse_runtime_branch("runtime/myhost-draft/")

    def test_nested_path_blocks(self):
        with self.assertRaises(ValueError):
            parse_runtime_branch("runtime/myhost-draft/company/lead-1")

    def test_whitespace_blocks(self):
        with self.assertRaises(ValueError):
            parse_runtime_branch("runtime/myhost-draft/lead one")

    def test_overlong_id_blocks(self):
        with self.assertRaises(ValueError):
            parse_runtime_branch("runtime/myhost-draft/" + "a" * 81)


if __name__ == "__main__":
    unittest.main()
