from __future__ import annotations

import socket
import unittest

from url_safety import is_public_http_url


def resolver_for(addresses):
    def resolve(host, port, type=socket.SOCK_STREAM):
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]
    return resolve


class UrlSafetyTests(unittest.TestCase):
    def test_allows_public_https_host(self):
        self.assertTrue(
            is_public_http_url(
                "https://example.com/contact",
                resolver=resolver_for(["93.184.216.34"]),
            )
        )

    def test_blocks_private_and_loopback_literals(self):
        for url in (
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://192.168.1.5/",
            "http://[::1]/",
        ):
            self.assertFalse(is_public_http_url(url))

    def test_blocks_local_hostname_and_embedded_credentials(self):
        self.assertFalse(is_public_http_url("http://localhost/"))
        self.assertFalse(is_public_http_url("https://user:pass@example.com/"))

    def test_blocks_dns_answer_when_any_address_is_non_global(self):
        self.assertFalse(
            is_public_http_url(
                "https://example.com/",
                resolver=resolver_for(["93.184.216.34", "127.0.0.1"]),
            )
        )

    def test_unresolvable_host_is_blocked(self):
        def failing_resolver(host, port, type=socket.SOCK_STREAM):
            raise socket.gaierror("not found")

        self.assertFalse(
            is_public_http_url("https://missing.example/", resolver=failing_resolver)
        )


if __name__ == "__main__":
    unittest.main()
