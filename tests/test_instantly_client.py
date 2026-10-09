import unittest

import requests

from instantly_client import FORBIDDEN_TOOL_NAMES, InstantlyClient, InstantlyError, inspect_campaign_sequence


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)
        self.content = b"{}" if status_code != 204 else b""
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def approved_batch():
    return {
        "schema_version": "leadscanner-approved-revalidation/1.0",
        "rows": [{
            "lead_id": "growth-aaaaaaaaaaaaaaaaaaaa",
            "company": "Acme",
            "website": "https://acme.nl/",
            "official_domain": "acme.nl",
            "email": "info@acme.nl",
            "status": "review_draft",
            "contact_basis_status": "review_required",
            "automatic_send": False,
            "subject": "idee voor afspraakroute",
            "body": "Hoi, ik zag jullie afspraakroute. Ik heb een klein voorstel.",
            "verified_observation": "Klanten kunnen online een afspraak aanvragen voor onderhoud of reparatie.",
            "verified_observation_source_url": "https://acme.nl/afspraak",
            "verified_observation_source_type": "official_site",
            "signal_type": "appointment",
            "value_first_action": "een korte voorbeeldvariant voor de afspraakroute",
        }],
        "safety": {
            "automatic_send": False,
            "dedupe_rechecked_immediately_before_mutation": True,
        },
    }


def campaign(*, steps=None, status=2):
    if steps is None:
        steps = [{
            "type": "email",
            "variants": [{"subject": "{{leadscanner_subject}}", "body": "{{leadscanner_body}}"}],
        }]
    return {"id": "c1", "status": status, "sequences": [{"steps": steps}]}


def approved_facts_batch():
    batch = approved_batch()
    batch["rows"][0].update({
        "review_mode": "instantly_sequence",
        "status": "sequence_facts_review",
        "subject": "",
        "body": "",
    })
    return batch


def evidence_three_steps():
    return [
        {"type": "email", "variants": [{
            "subject": "Vraag", "body": "Ik zag {{leadscanner_observation}}.",
        }]},
        {"type": "email", "variants": [{
            "subject": "Een voorstel", "body": "Een idee: {{leadscanner_value_action}}.",
        }]},
        {"type": "email", "variants": [{
            "subject": "Vervolg", "body": "Laat gerust weten als dit niet relevant is.",
        }]},
    ]


def approval_for(target):
    return (
        "APPROVE_INSTANTLY_SEQUENCE "
        + target["id"] + " " + inspect_campaign_sequence(target)["sequence_fingerprint"]
    )


class InstantlyClientTests(unittest.TestCase):
    def test_nested_liquid_in_verified_website_observation_is_blocked(self):
        from instantly_client import approved_custom_variables
        for malicious in (
            "{{sendingAccountEmail}}",
            "{% if sendingAccountName %}private{% endif %}",
            "stray }} template close",
        ):
            item = {**approved_batch()["rows"][0], "verified_observation": malicious}
            with self.assertRaisesRegex(ValueError, "nested_template_markup_forbidden"):
                approved_custom_variables(item)

    def test_nested_template_in_reviewed_subject_or_body_is_blocked(self):
        from instantly_client import approved_custom_variables
        for field, value in (("subject","{{firstName}}"),("body","Hi {% assign hidden = 1 %}")):
            item = {**approved_batch()["rows"][0], field: value}
            with self.assertRaisesRegex(ValueError, "nested_template_markup_forbidden"):
                approved_custom_variables(item)

    def test_reviewed_facts_without_nested_syntax_remain_valid(self):
        from instantly_client import approved_custom_variables
        variables = approved_custom_variables(approved_batch()["rows"][0])
        self.assertIn("leadscanner_subject", variables)
        self.assertIn("leadscanner_body", variables)
        self.assertIn("leadscanner_observation", variables)
        self.assertIn("leadscanner_value_action", variables)

    def test_fact_only_draft_three_step_stages_without_email_copy(self):
        target = campaign(steps=evidence_three_steps(), status=0)
        session = FakeSession([
            FakeResponse(payload=target),
            FakeResponse(payload={"id": "instantly-lead-1"}),
        ])
        client = InstantlyClient("secret", session=session)
        client.add_approved_lead_to_campaign(
            approved_batch=approved_facts_batch(),
            lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
            campaign_id="c1",
            registry_rows=[],
            sequence_approval=approval_for(target),
        )
        self.assertEqual([call[0] for call in session.calls], ["GET", "POST"])
        vars = session.calls[1][2]["json"]["custom_variables"]
        self.assertNotIn("leadscanner_subject", vars)
        self.assertNotIn("leadscanner_body", vars)
        self.assertEqual(vars["leadscanner_observation"], approved_batch()["rows"][0]["verified_observation"])
        self.assertEqual(vars["leadscanner_value_action"], approved_batch()["rows"][0]["value_first_action"])

    def test_fact_only_requires_explicit_campaign_fingerprint_approval(self):
        target = campaign(steps=evidence_three_steps(), status=0)
        session = FakeSession([FakeResponse(payload=target)])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "instantly_sequence_approval_required"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_facts_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(session.calls, [])

    def test_fact_only_rejects_changed_campaign_fingerprint(self):
        target = campaign(steps=evidence_three_steps(), status=0)
        changed = campaign(steps=evidence_three_steps(), status=0)
        changed["sequences"][0]["steps"][2]["variants"][0]["body"] += " gewijzigd"
        session = FakeSession([FakeResponse(payload=changed)])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "instantly_sequence_approval_fingerprint_mismatch"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_facts_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
                sequence_approval=approval_for(target),
            )
        self.assertEqual(len(session.calls), 1)

    def test_fact_only_rejects_paused_and_active_campaigns(self):
        for status in (1, 2):
            target = campaign(steps=evidence_three_steps(), status=status)
            session = FakeSession([FakeResponse(payload=target)])
            client = InstantlyClient("secret", session=session)
            with self.assertRaisesRegex(ValueError, "campaign_must_be_draft_or_paused|sequence_campaign_must_be_draft"):
                client.add_approved_lead_to_campaign(
                    approved_batch=approved_facts_batch(),
                    lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                    campaign_id="c1",
                    registry_rows=[],
                    sequence_approval=approval_for(target),
                )
            self.assertEqual(len(session.calls), 1)

    def test_fact_only_rejects_one_step_and_unmapped_variables(self):
        for steps in (
            evidence_three_steps()[:1],
            [
                {**step, "variants": [dict(step["variants"][0])]}
                for step in evidence_three_steps()
            ],
        ):
            if len(steps) == 3:
                steps[0]["variants"][0]["body"] += " {{aiIdeas}}"
            target = campaign(steps=steps, status=0)
            session = FakeSession([FakeResponse(payload=target)])
            client = InstantlyClient("secret", session=session)
            with self.assertRaisesRegex(ValueError, "approved_three_step_evidence_sequence_required|campaign_personalization_variable_missing"):
                client.add_approved_lead_to_campaign(
                    approved_batch=approved_facts_batch(),
                    lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                    campaign_id="c1",
                    registry_rows=[],
                    sequence_approval=approval_for(target),
                )
            self.assertEqual(len(session.calls), 1)

    def test_fact_only_rejects_unapproved_generated_copy(self):
        batch = approved_facts_batch()
        batch["rows"][0]["body"] = "Unapproved mail"
        target = campaign(steps=evidence_three_steps(), status=0)
        session = FakeSession([FakeResponse(payload=target)])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "sequence_facts_must_not_include_mail_copy"):
            client.add_approved_lead_to_campaign(
                approved_batch=batch,
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
                sequence_approval=approval_for(target),
            )
        self.assertEqual(len(session.calls), 1)


    def test_read_methods_use_v2_and_bearer(self):
        session = FakeSession([FakeResponse(payload={"items": []})])
        client = InstantlyClient("secret", session=session)
        client.list_campaigns(limit=10)
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.instantly.ai/api/v2/campaigns")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")

    def test_safe_read_retries_once_on_429_without_leaking_body(self):
        sleeps = []
        session = FakeSession([
            FakeResponse(status_code=429, payload={"message": "sensitive detail"}, headers={"Retry-After": "0"}),
            FakeResponse(payload={"items": []}),
        ])
        client = InstantlyClient("secret", session=session, sleep_fn=sleeps.append)
        result = client.list_campaigns(limit=10)
        self.assertEqual(result, {"items": []})
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleeps, [0.0])

    def test_write_does_not_retry_on_server_error(self):
        session = FakeSession([
            FakeResponse(payload=campaign()),
            FakeResponse(status_code=503, payload={"message": "do not repeat this write"}),
        ])
        client = InstantlyClient("secret", session=session, sleep_fn=lambda _: None)
        with self.assertRaisesRegex(InstantlyError, "status=503"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 2)

    def test_write_timeout_reports_unknown_outcome(self):
        class TimeoutSession:
            def request(self, method, url, **kwargs):
                raise requests.Timeout("synthetic timeout")

        client = InstantlyClient("secret", session=TimeoutSession())
        with self.assertRaisesRegex(InstantlyError, "write_outcome_unknown"):
            client._request("POST", "/leads", json={"email": "lead@example.com"})

    def test_api_error_does_not_include_response_body(self):
        session = FakeSession([
            FakeResponse(status_code=400, payload={"message": "private lead content"}),
        ])
        client = InstantlyClient("secret", session=session, sleep_fn=lambda _: None)
        with self.assertRaises(InstantlyError) as caught:
            client.list_campaigns(limit=10)
        self.assertIn("status=400", str(caught.exception))
        self.assertNotIn("private lead content", str(caught.exception))

    def test_campaign_error_exposes_only_allowlisted_schema_hints(self):
        session = FakeSession([FakeResponse(status_code=400, payload={
            "message": "campaign_schedule timezone invalid - hello@example.org private code sk_TEST"
        })])
        client = InstantlyClient("secret", session=session)
        with self.assertRaises(InstantlyError) as caught:
            client._request("POST", "/campaigns", json={"name": "Sample"})
        message = str(caught.exception)
        self.assertIn("campaign_schedule", message)
        self.assertIn("timezone", message)
        self.assertNotIn("hello@example.org", message)
        self.assertNotIn("sk_TEST", message)

    def test_email_reads_support_cursor_pagination(self):
        session = FakeSession([FakeResponse(payload={"items": [], "next_starting_after": None})])
        client = InstantlyClient("secret", session=session)
        client.get_emails(
            campaign_id="c1",
            received_only=True,
            limit=25,
            starting_after="cursor-1",
        )
        method, url, kwargs = session.calls[0]
        self.assertEqual((method, url), ("GET", "https://api.instantly.ai/api/v2/emails"))
        self.assertEqual(kwargs["params"]["campaign_id"], "c1")
        self.assertEqual(kwargs["params"]["email_type"], "received")
        self.assertEqual(kwargs["params"]["starting_after"], "cursor-1")

    def test_list_leads_supports_official_contact_and_list_filters(self):
        session = FakeSession([FakeResponse(payload={"items": []})])
        client = InstantlyClient("secret", session=session)
        client.list_leads(
            campaign="c1",
            list_id="list-1",
            contacts=["Lead@Example.com"],
            limit=25,
            starting_after="cursor-1",
        )
        method, url, kwargs = session.calls[0]
        self.assertEqual((method, url), ("POST", "https://api.instantly.ai/api/v2/leads/list"))
        self.assertEqual(kwargs["json"]["campaign"], "c1")
        self.assertEqual(kwargs["json"]["list_id"], "list-1")
        self.assertEqual(kwargs["json"]["contacts"], ["lead@example.com"])
        self.assertEqual(kwargs["json"]["starting_after"], "cursor-1")

    def test_add_requires_draft_or_paused_campaign(self):
        session = FakeSession([FakeResponse(payload={"id": "c1", "status": 1})])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "draft_or_paused"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_add_approved_lead_uses_workspace_dedupe_flags(self):
        session = FakeSession([
            FakeResponse(payload=campaign()),
            FakeResponse(payload={"id": "instantly-lead-1"}),
        ])
        client = InstantlyClient("secret", session=session)
        result = client.add_approved_lead_to_campaign(
            approved_batch=approved_batch(),
            lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
            campaign_id="c1",
            registry_rows=[],
        )
        self.assertEqual(result["id"], "instantly-lead-1")
        method, url, kwargs = session.calls[1]
        self.assertEqual((method, url), ("POST", "https://api.instantly.ai/api/v2/leads"))
        self.assertTrue(kwargs["json"]["skip_if_in_workspace"])
        self.assertTrue(kwargs["json"]["skip_if_in_campaign"])
        self.assertEqual(
            kwargs["json"]["custom_variables"]["leadscanner_subject"],
            approved_batch()["rows"][0].get("subject", ""),
        )
        self.assertEqual(
            kwargs["json"]["custom_variables"]["leadscanner_body"],
            approved_batch()["rows"][0].get("body", ""),
        )
        self.assertEqual(
            kwargs["json"]["custom_variables"]["leadscanner_observation"],
            approved_batch()["rows"][0]["verified_observation"],
        )
        self.assertEqual(
            kwargs["json"]["custom_variables"]["leadscanner_evidence_url"],
            "https://acme.nl/afspraak",
        )


    def test_staging_rechecks_provider_blocklist_before_create(self):
        for blocked in ("info@acme.nl", "acme.nl"):
            with self.subTest(blocked=blocked):
                session=FakeSession([
                    FakeResponse(payload=campaign()),
                    FakeResponse(payload={"items":[{"bl_value":blocked}],"next_starting_after":None}),
                ])
                client=InstantlyClient("secret",session=session)
                with self.assertRaisesRegex(ValueError,"provider_blocklist_blocks_stage"):
                    client.add_approved_lead_to_campaign(
                        approved_batch=approved_batch(),
                        lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                        campaign_id="c1",
                        registry_rows=[],
                    )
                self.assertFalse(any(method=="POST" and url.endswith("/leads") for method,url,_ in session.calls))

    def test_staging_rejects_blocklist_api_failure_without_write(self):
        session=FakeSession([
            FakeResponse(payload=campaign()),
            FakeResponse(status_code=503,payload={"message":"private"}),
            FakeResponse(status_code=503,payload={"message":"private"}),
        ])
        client=InstantlyClient("secret",session=session,sleep_fn=lambda _:None)
        with self.assertRaisesRegex(InstantlyError,"instantly_api_error status=503"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertFalse(any(method=="POST" and url.endswith("/leads") for method,url,_ in session.calls))

    def test_legacy_copy_can_use_guarded_optional_fact_fields(self):
        from instantly_campaign_copy import campaign_steps
        from instantly_client import validate_campaign_personalization
        for lang in ("nl", "en"):
            c={"id":"draft-id","status":0,"sequences":[{"steps":campaign_steps(lang)}]}
            validate_campaign_personalization(
                c, {"leadscanner_subject":"approved subject","leadscanner_body":"approved body"},
                review_mode="reviewed_mail",
            )

    def test_unprotected_optional_fact_field_rejected_for_reviewed_copy(self):
        from instantly_campaign_copy import campaign_steps
        from instantly_client import validate_campaign_personalization
        steps=campaign_steps("nl")
        steps[2]["variants"][0]["body"] += "\n{{leadscanner_value_action}}"
        c={"id":"draft-id","status":0,"sequences":[{"steps":steps}]}
        with self.assertRaisesRegex(ValueError,"optional_evidence_unprotected"):
            validate_campaign_personalization(
                c, {"leadscanner_subject":"approved subject","leadscanner_body":"approved body"},
                review_mode="reviewed_mail",
            )

    def test_legacy_reviewed_mail_cannot_bypass_sequence_fingerprint_approval(self):
        session = FakeSession([FakeResponse(payload=campaign(steps=evidence_three_steps(), status=0))])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "reviewed_mail_campaign_must_use_approved_copy"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_legacy_reviewed_mail_requires_both_copy_placeholders(self):
        steps = [{"type": "email", "variants": [{
            "subject": "Static subject", "body": "{{leadscanner_body}}",
        }]}]
        session = FakeSession([FakeResponse(payload=campaign(steps=steps))])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "reviewed_mail_campaign_must_use_approved_copy"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_uuid_named_template_variables_are_not_silently_ignored(self):
        uuid_variable = "f9e0556e-45ed-42ec-8494-1c5301628242_email_1"
        steps = [{"type": "email", "variants": [{
            "subject": "Vraag", "body": "{{leadscanner_observation}} {{" + uuid_variable + "}}",
        }]}]
        report = inspect_campaign_sequence(campaign(steps=steps))
        self.assertEqual(report["decision"], "unresolved_template_fields")
        self.assertEqual(report["unresolved_template_variables"], [uuid_variable])
        session = FakeSession([FakeResponse(payload=campaign(steps=steps))])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "campaign_personalization_variable_missing"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_malformed_variable_syntax_fails_closed(self):
        steps = [{"type": "email", "variants": [{
            "subject": "Vraag", "body": "{{leadscanner_observation} extra",
        }]}]
        with self.assertRaisesRegex(ValueError, "campaign_template_syntax_unrecognized"):
            inspect_campaign_sequence(campaign(steps=steps))

    def test_unmapped_ai_ideas_field_blocks_lead_write(self):
        steps = [{"type": "email", "variants": [{
            "subject": "Vraag", "body": "{{leadscanner_observation}} {{aiIdeas}}",
        }]}]
        report = inspect_campaign_sequence(campaign(steps=steps))
        self.assertEqual(report["decision"], "unresolved_template_fields")
        self.assertEqual(report["unresolved_template_variables"], ["aiIdeas"])
        session = FakeSession([FakeResponse(payload=campaign(steps=steps))])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "campaign_personalization_variable_missing"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_unmapped_first_name_is_not_assumed_to_exist(self):
        steps = [{"type": "email", "variants": [{
            "subject": "Vraag", "body": "Hallo {{firstName}} {{leadscanner_observation}}",
        }]}]
        report = inspect_campaign_sequence(campaign(steps=steps))
        self.assertEqual(report["unresolved_template_variables"], ["firstName"])

    def test_sequence_fingerprint_changes_with_email_copy_not_campaign_state(self):
        base = campaign()
        report = inspect_campaign_sequence(base)
        self.assertEqual(len(report["sequence_fingerprint"]), 64)
        self.assertEqual(
            report["sequence_fingerprint"],
            inspect_campaign_sequence(campaign(status=0))["sequence_fingerprint"],
        )
        changed = campaign(steps=[{
            "type": "email",
            "variants": [{"subject": "{{leadscanner_subject}}", "body": "{{leadscanner_body}} extra"}],
        }])
        self.assertNotEqual(report["sequence_fingerprint"], inspect_campaign_sequence(changed)["sequence_fingerprint"])

    def test_campaign_id_mismatch_blocks_lead_write(self):
        session = FakeSession([FakeResponse(payload={**campaign(), "id": "wrong"})])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(RuntimeError, "campaign_readback_id_mismatch"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_unknown_template_variable_blocks_lead_write(self):
        steps = [{"type": "email", "variants": [{
            "subject": "Hallo", "body": "{{leadscanner_not_supplied}}",
        }]}]
        session = FakeSession([FakeResponse(payload=campaign(steps=steps))])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "campaign_personalization_variable_missing"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_generic_campaign_without_leadscanner_variable_is_blocked(self):
        steps = [{"type": "email", "variants": [{"subject": "Hallo", "body": "Een algemeen aanbod."}]}]
        session = FakeSession([FakeResponse(payload=campaign(steps=steps))])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "campaign_leadscanner_personalization_required"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_third_party_evidence_is_blocked_before_lead_write(self):
        batch = approved_batch()
        batch["rows"][0]["verified_observation_source_type"] = "directory"
        session = FakeSession([FakeResponse(payload=campaign())])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "verified_first_party_personalization_required"):
            client.add_approved_lead_to_campaign(
                approved_batch=batch,
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_off_domain_evidence_is_blocked_before_lead_write(self):
        batch = approved_batch()
        batch["rows"][0]["verified_observation_source_url"] = "https://unrelated.example/afspraak"
        session = FakeSession([FakeResponse(payload=campaign())])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "personalization_evidence_domain_mismatch"):
            client.add_approved_lead_to_campaign(
                approved_batch=batch,
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_campaign_without_sequences_blocks_lead_write(self):
        session = FakeSession([FakeResponse(payload={"id": "c1", "status": 2})])
        client = InstantlyClient("secret", session=session)
        with self.assertRaisesRegex(ValueError, "campaign_email_sequence_required"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=[],
            )
        self.assertEqual(len(session.calls), 1)

    def test_sequence_audit_shows_legacy_copy_dependency_without_email_text(self):
        report = inspect_campaign_sequence(campaign())
        self.assertEqual(report["email_step_count"], 1)
        self.assertEqual(report["email_variant_count"], 1)
        self.assertTrue(report["reviewed_copy_required"])
        self.assertEqual(report["decision"], "reviewed_mail_copy_still_required")
        self.assertNotIn("Hoi", str(report))

    def test_sequence_audit_detects_original_three_step_ai_template(self):
        steps = [
            {"type": "email", "variants": [
                {"subject": "Vraagje", "body": "Hi {{firstName}}, {{aiIdeas}}"},
                {"subject": "Voorstel", "body": "Hallo {{companyName}}, {{aiIdeas}}"},
            ]} for _ in range(3)
        ]
        report = inspect_campaign_sequence(campaign(steps=steps))
        self.assertEqual(report["email_step_count"], 3)
        self.assertEqual(report["email_variant_count"], 6)
        self.assertEqual(report["leadscanner_variables"], [])
        self.assertIn("aiIdeas", report["other_template_variables"])
        self.assertEqual(report["unresolved_template_variables"], ["aiIdeas", "firstName"])
        self.assertEqual(report["decision"], "not_linked_to_leadscanner")
        self.assertFalse(report["evidence_only_template_candidate"])

    def test_sequence_audit_marks_evidence_only_template_as_candidate(self):
        steps = [
            {"type": "email", "variants": [
                {"subject": "Vraag", "body": "{{leadscanner_observation}}"},
            ]},
            {"type": "email", "variants": [
                {"subject": "Idee", "body": "{{leadscanner_value_action}}"},
            ]},
            {"type": "email", "variants": [
                {"subject": "Vervolg", "body": "Kan ik dit toelichten?"},
            ]},
        ]
        report = inspect_campaign_sequence(campaign(steps=steps))
        self.assertEqual(report["email_step_count"], 3)
        self.assertEqual(report["decision"], "evidence_only_template_candidate")
        self.assertTrue(report["evidence_only_template_candidate"])
        self.assertFalse(report["reviewed_copy_required"])

    def test_sequence_audit_rejects_stray_closing_template_braces(self):
        for body in (
            "Hello }} without opening",
            "Hello {{leadscanner_observation}} and }}",
            "Hello {{leadscanner_observation}} and {{broken",
        ):
            with self.subTest(body=body):
                target = campaign(steps=[{
                    "type": "email",
                    "variants": [{"subject": "Hello", "body": body}],
                }])
                with self.assertRaisesRegex(ValueError, "campaign_template_syntax_unrecognized"):
                    inspect_campaign_sequence(target)

    def test_sequence_audit_rejects_malformed_variant(self):
        with self.assertRaisesRegex(ValueError, "campaign_email_body_required"):
            inspect_campaign_sequence(campaign(steps=[
                {"type": "email", "variants": [{"subject": "Vraag", "body": ""}]},
            ]))

    def test_live_registry_match_blocks_write(self):
        session = FakeSession([])
        client = InstantlyClient("secret", session=session)
        registry = [{
            "identity": {
                "company": "acme",
                "domains": {"acme.nl"},
                "emails": {"info@acme.nl"},
                "lead_ids": set(),
            },
            "status": "concept",
            "row_number": 2,
        }]
        with self.assertRaisesRegex(ValueError, "live_dedupe_match"):
            client.add_approved_lead_to_campaign(
                approved_batch=approved_batch(),
                lead_id="growth-aaaaaaaaaaaaaaaaaaaa",
                campaign_id="c1",
                registry_rows=registry,
            )
        self.assertEqual(session.calls, [])

    def test_no_sending_tools_are_exposed(self):
        for name in FORBIDDEN_TOOL_NAMES:
            self.assertFalse(hasattr(InstantlyClient, name), name)



    def test_liquid_else_must_not_use_missing_optional_fact(self):
        from instantly_client import validate_campaign_personalization
        steps = [
            {"type":"email","variants":[{"subject":"{{leadscanner_subject}}","body":"{{leadscanner_body}}"}]},
            {"type":"email","variants":[{"subject":"","body":
                "{% if leadscanner_observation %}Observed {{leadscanner_observation}}"
                "{% else %}Fallback {{leadscanner_value_action}}{% endif %}"}]},
        ]
        target = {"id":"draft-id","status":0,"sequences":[{"steps":steps}]}
        with self.assertRaisesRegex(ValueError,"optional_evidence_unprotected"):
            validate_campaign_personalization(
                target,{"leadscanner_subject":"Approved","leadscanner_body":"Reviewed"},
                review_mode="reviewed_mail",
            )

    def test_spaced_unguarded_optional_variable_is_rejected(self):
        from instantly_client import validate_campaign_personalization
        steps = [
            {"type":"email","variants":[{"subject":"{{leadscanner_subject}}","body":"{{leadscanner_body}}"}]},
            {"type":"email","variants":[{"subject":"","body":
                "{% if leadscanner_observation %}Saw {{leadscanner_observation}}{% endif %}"
                "Outside guard: {{ leadscanner_value_action }}"}]},
        ]
        target = {"id":"draft-id","status":0,"sequences":[{"steps":steps}]}
        with self.assertRaisesRegex(ValueError,"optional_evidence_unprotected"):
            validate_campaign_personalization(
                target,{"leadscanner_subject":"Approved","leadscanner_body":"Reviewed"},
                review_mode="reviewed_mail",
            )

if __name__ == "__main__":
    unittest.main()
