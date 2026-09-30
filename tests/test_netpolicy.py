"""Path decisions. No Docker network is created."""

from __future__ import annotations

import unittest

from netpolicy.paths import (
    advisor_can_open,
    app_can_open,
    browser_can_open,
    executor_can_open,
    vet_adopted,
)


class NetpolicyTests(unittest.TestCase):
    def test_an_app_opens_the_webhook_receiver_only(self) -> None:
        self.assertEqual(app_can_open("webhooks", 8080).reason, "webhook")
        self.assertEqual(app_can_open("webhooks", 80).reason, "not_the_webhook")
        for name in ("postgres", "qdrant", "executor", "friday", "memory-mcp", "gateway", "ollama", "board"):
            decision = app_can_open(name, 5432)
            self.assertEqual(decision.reason, "core_closed", name)
        self.assertEqual(app_can_open("http://friday:8080", 8080).reason, "core_closed")

    def test_the_executor_health_checks_an_app_name(self) -> None:
        self.assertEqual(executor_can_open("jellyfin", 8096).reason, "health")
        self.assertEqual(executor_can_open("postgres", 5432).reason, "not_an_app")
        self.assertEqual(executor_can_open("jellyfin", True).reason, "not_an_app")

    def test_an_advisor_uses_the_gateway_when_the_wire_allows_it(self) -> None:
        self.assertEqual(
            advisor_can_open("gateway", 8090, wire_allows=True).reason,
            "gateway",
        )
        self.assertEqual(
            advisor_can_open("gateway", 8090, wire_allows=False).reason,
            "wire_closed",
        )
        self.assertEqual(
            advisor_can_open("jellyfin", 8096, wire_allows=True).reason,
            "not_the_gateway",
        )

    def test_the_browser_has_the_internet_and_no_core(self) -> None:
        self.assertEqual(browser_can_open("postgres").reason, "core_closed")
        self.assertEqual(browser_can_open("example.com").reason, "internet")
        self.assertEqual(browser_can_open("169.254.169.254").reason, "link_local")

    def test_an_adopted_url_refuses_core_link_local_and_metadata(self) -> None:
        self.assertEqual(vet_adopted("postgres").reason, "core_closed")
        self.assertEqual(vet_adopted("http://Qdrant:6333").reason, "core_closed")
        self.assertEqual(vet_adopted("memory-mcp").reason, "core_closed")
        self.assertEqual(vet_adopted("gateway").reason, "core_closed")
        self.assertEqual(vet_adopted("169.254.169.254").reason, "link_local")
        self.assertEqual(vet_adopted("fe80::1").reason, "link_local")
        self.assertEqual(vet_adopted("metadata.google.internal").reason, "metadata")
        self.assertEqual(
            vet_adopted("example.com", ["169.254.169.254"]).reason,
            "link_local",
        )
        self.assertEqual(vet_adopted("postgres", ["8.8.8.8"]).reason, "core_closed")

    def test_a_private_lan_address_can_be_adopted(self) -> None:
        self.assertEqual(vet_adopted("192.168.1.20").reason, "adopted")
        self.assertEqual(vet_adopted("http://10.0.0.5:32400").reason, "adopted")
        self.assertEqual(vet_adopted("example.com", ["192.168.1.20"]).reason, "adopted")
        self.assertEqual(browser_can_open("192.168.1.20").reason, "internet")


if __name__ == "__main__":
    unittest.main()
