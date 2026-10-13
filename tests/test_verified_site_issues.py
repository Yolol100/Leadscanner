import unittest

from verified_site_issues import markup_issues, verified_broken_link


class VerifiedIssueTests(unittest.TestCase):
    def test_static_unlabeled_form_and_image_link_are_observable(self):
        html = ('<form><input type="email" id="email"></form>'
                '<a href="/winkel"><img src="shop.png"></a>')
        issues = markup_issues(html, "https://example.nl/contact")
        self.assertEqual([x["category"] for x in issues],
                         ["unlabeled_form_control", "unnamed_image_link"])
        self.assertTrue(all(x["source_type"] == "official_site" for x in issues))

    def test_explicit_and_nested_labels_prevent_false_positive(self):
        html = ('<form><label for="mail">Email</label><input id="mail">'
                '<label>Bericht <textarea></textarea></label></form>'
                '<a href="/"><img src="logo.png" alt="Home"></a>')
        self.assertEqual(markup_issues(html, "https://example.nl/contact"), [])

    def test_aria_labels_prevent_false_positive(self):
        html = ('<form><input type="text" aria-labelledby="name"></form>'
                '<a aria-label="Winkel" href="/winkel"><img src="shop.png"></a>')
        self.assertEqual(markup_issues(html, "https://example.nl"), [])

    def test_broken_link_requires_repeat_check_in_caller(self):
        issue = verified_broken_link("https://example.nl/diensten",
                                     "https://example.nl/removed?private=1")
        self.assertIn("/removed", issue["observation_nl"])
        self.assertNotIn("private", issue["observation_nl"])
        self.assertEqual(issue["severity"], 100)


if __name__ == "__main__":
    unittest.main()
