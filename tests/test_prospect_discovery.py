import importlib.util
import pathlib
import sys
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "prospect_discovery.py"
spec = importlib.util.spec_from_file_location("prospect_discovery", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class ProspectDiscoveryTests(unittest.TestCase):
    def test_directory_page_extracts_external_business_links_only(self):
        source = module.SourceSpec(source_id="nl-agencies", source_type="directory_page", source_url="https://directory.example/list", max_candidates=10, approved=True)
        page = module.parse_page("""<html><body><a href='/internal'>internal</a><a href='https://bedrijf-a.nl/diensten'>Bedrijf A</a><a href='https://www.bedrijf-a.nl/contact'>duplicate</a><a href='https://linkedin.com/company/x'>social</a><a href='https://bedrijf-b.nl'>Bedrijf B</a></body></html>""", source.source_url)
        result = module.source_candidate_urls(source, page)
        self.assertEqual([module.host_key(url) for url, _ in result], ["bedrijf-a.nl", "bedrijf-b.nl"])

    def test_directory_page_skips_related_org_and_deprioritizes_navigation(self):
        source = module.SourceSpec(source_id="directory", source_type="directory_page", source_url="https://portal.directory.example/list", max_candidates=2, approved=True)
        page = module.parse_page("""<html><body>
            <a href='https://directory.example/about'>About</a>
            <a href='https://tracking.example/privacy'>Privacy</a>
            <a href='https://company-a.example/'>Visit Website</a>
            <a href='https://company-b.example/'>Company B</a>
        </body></html>""", source.source_url)
        result = module.source_candidate_urls(source, page)
        self.assertEqual([module.host_key(url) for url, _ in result], ["company-a.example", "company-b.example"])

    def test_seed_site_discovers_company_but_defers_contact_lookup(self):
        source = module.SourceSpec(source_id="seed-1", source_type="seed_site", source_url="https://voorbeeld.nl/", include_terms=("wordpress",), approved=True)
        pages={"https://voorbeeld.nl/":"<html><head><meta property='og:site_name' content='Voorbeeld BV'></head><body>WordPress bureau</body></html>"}
        def fetch(url):
            if url in pages: return pages[url]
            raise module.DiscoveryError("missing fixture")
        result=module.discover_source(source, fetch)
        self.assertEqual(len(result),1); self.assertEqual(result[0].company,"Voorbeeld BV"); self.assertIn("contact lookup intentionally deferred",result[0].reason); self.assertEqual(result[0].matched_terms,("wordpress",))

    def test_include_exclude_terms_are_fail_closed(self):
        accepted,matched=module.match_terms("WordPress en WooCommerce",["wordpress"],["casino"])
        self.assertTrue(accepted); self.assertEqual(matched,("wordpress",)); self.assertFalse(module.match_terms("WordPress casino",["wordpress"],["casino"])[0]); self.assertFalse(module.match_terms("Shopify",["wordpress"],[])[0])

    def test_existing_domains_dedupes_leadlijst_and_candidates(self):
        self.assertEqual(module.existing_domains([{"Website":"https://www.example.nl/a"}],[{"website":"example.com"}]), {"example.nl","example.com"})

    def test_source_requires_explicit_approval_to_discover(self):
        source=module.SourceSpec(source_id="blocked",source_type="seed_site",source_url="https://example.nl/",approved=False)
        self.assertEqual(module.discover_source(source,lambda url:"<html></html>"),[])

    def test_private_network_targets_are_rejected_without_dns(self):
        for target in ("127.0.0.1","10.1.2.3","169.254.169.254","localhost"):
            self.assertFalse(module.is_public_network_target(target))

    def test_directory_index_follows_bounded_profile_then_official_site(self):
        source=module.SourceSpec(source_id="members",source_type="directory_index",source_url="https://directory.example/members",max_candidates=5,approved=True)
        pages={"https://directory.example/members":"<a href='/members/acme'>Acme</a>","https://directory.example/members/acme":"<a href='https://acme.example/'>Website</a>","https://acme.example/":"<meta property='og:site_name' content='Acme'><p>Webdesign</p>"}
        def fetch(url):
            if url in pages: return pages[url]
            raise module.DiscoveryError("missing fixture")
        result=module.discover_source(source,fetch); self.assertEqual(len(result),1); self.assertEqual(result[0].website,"https://acme.example/")

    def test_directory_index_prioritizes_member_profile_over_navigation(self):
        source=module.SourceSpec(source_id="members",source_type="directory_index",source_url="https://directory.example/members",max_candidates=1,approved=True)
        pages={
            "https://directory.example/members":"<a href='/contact'>Contact</a><a href='/events'>Events</a><a href='/members/acme'>Acme member</a>",
            "https://directory.example/members/acme":"<a href='https://acme.example/'>Visit Website</a>",
            "https://acme.example/":"<meta property='og:site_name' content='Acme'><p>Industrial systems</p>",
        }
        def fetch(url):
            if url in pages: return pages[url]
            raise module.DiscoveryError("missing fixture")
        result=module.discover_source(source,fetch)
        self.assertEqual([item.website for item in result],["https://acme.example/"])

    def test_known_hosts_do_not_consume_source_output_quota(self):
        source=module.SourceSpec(source_id="directory",source_type="directory_page",source_url="https://directory.example/list",max_candidates=2,approved=True)
        pages={
            "https://directory.example/list":"<a href='https://known.example/'>Visit Website</a><a href='https://new-a.example/'>Visit Website</a><a href='https://new-b.example/'>Visit Website</a>",
            "https://new-a.example/":"<meta property='og:site_name' content='New A'><p>Manufacturing</p>",
            "https://new-b.example/":"<meta property='og:site_name' content='New B'><p>Manufacturing</p>",
        }
        fetched=[]
        def fetch(url):
            fetched.append(url)
            if url in pages: return pages[url]
            raise module.DiscoveryError("missing fixture")
        result, skipped=module.discover_source_with_stats(source,fetch,known_hosts={"known.example"})
        self.assertEqual(skipped,1)
        self.assertEqual([item.website for item in result],["https://new-a.example/","https://new-b.example/"])
        self.assertNotIn("https://known.example/",fetched)

    def test_candidate_id_is_stable(self):
        candidate=module.Candidate(company="Example",website="https://example.nl/",source_url="https://directory.example/",source_id="s1",source_type="directory_page",country="NL",matched_terms=(),reason="test")
        self.assertEqual(candidate.candidate_id,candidate.candidate_id); self.assertTrue(candidate.candidate_id.startswith("prospect-"))


if __name__ == "__main__": unittest.main()
