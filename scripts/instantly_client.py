#!/usr/bin/env python3
"""Minimal fail-closed Instantly API v2 adapter for Leadscanner.

This module deliberately exposes no campaign activation, email send, reply,
forward, test-send, warmup mutation, or sequence mutation operation.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import quote, urlparse

import requests

from dedupe_preflight import domains_match, match_candidate, normalize_domain

BASE_URL = "https://api.instantly.ai/api/v2"
SAFE_CAMPAIGN_STATUSES = {0, 2}  # Draft, Paused
LEAD_ID_RE = re.compile(r"^growth-[0-9a-f]{20}$")
VARIABLE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
# Only these fields are guaranteed by the lead payload, not by Instantly enrichment.
GUARANTEED_STANDARD_VARIABLES = frozenset({"email", "companyName", "website"})


def approved_custom_variables(row: dict) -> dict[str, str]:
    """Keep reviewed legacy copy and expose only verified official-site facts."""
    lead_id = str(row.get("lead_id") or "").strip()
    subject = str(row.get("subject") or "").strip()
    body = str(row.get("body") or "").strip()
    mode = str(row.get("review_mode") or "reviewed_mail").strip()
    if mode not in {"reviewed_mail", "instantly_sequence"}:
        raise ValueError("unsupported_review_mode")
    if mode == "instantly_sequence":
        if not lead_id:
            raise ValueError("approved_lead_id_required")
        if row.get("status") != "sequence_facts_review" or subject or body:
            raise ValueError("sequence_facts_must_not_include_mail_copy")
    elif not lead_id or not subject or not body:
        raise ValueError("reviewed_lead_copy_required")
    variables = {
        "leadscanner_lead_id": lead_id,
        "leadscanner_review_status": "approved",
    }
    if mode == "reviewed_mail":
        variables.update({
            "leadscanner_subject": subject,
            "leadscanner_body": body,
        })

    observation = str(row.get("verified_observation") or "").strip()
    evidence_url = str(row.get("verified_observation_source_url") or "").strip()
    source_type = str(row.get("verified_observation_source_type") or "").strip()
    value_action = str(row.get("value_first_action") or "").strip()
    signal_type = str(row.get("signal_type") or "").strip()
    if mode == "instantly_sequence" and not all((
        observation, evidence_url, value_action, signal_type,
    )):
        raise ValueError("sequence_facts_require_verified_personalization")
    if any((observation, evidence_url, source_type, value_action, signal_type)):
        if not all((observation, evidence_url, value_action)) or source_type != "official_site":
            raise ValueError("verified_first_party_personalization_required")
        parsed = urlparse(evidence_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or not domains_match(
                normalize_domain(evidence_url),
                normalize_domain(row.get("official_domain")),
            )
        ):
            raise ValueError("personalization_evidence_domain_mismatch")
        variables.update({
            "leadscanner_observation": observation,
            "leadscanner_evidence_url": evidence_url,
            "leadscanner_value_action": value_action,
        })
        if signal_type:
            variables["leadscanner_signal_type"] = signal_type
    # Never allow content copied from websites or reviewed mail to become a
    # second, unreviewed Instantly/Liquid template. Only campaign-owned code
    # may contain merge delimiters; lead values must remain literal plain text.
    for key in ("leadscanner_subject", "leadscanner_body",
                "leadscanner_observation", "leadscanner_value_action"):
        value = variables.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or any(
            sequence in value for sequence in ("{{", "}}", "{%", "%}")
        ):
            raise ValueError("reviewed_lead_nested_template_markup_forbidden")
        if "\x00" in value:
            raise ValueError("reviewed_lead_nul_character_forbidden")
    return variables


def inspect_campaign_sequence(campaign: dict) -> dict:
    """Audit sequence shape and merge-field names without exposing email copy."""
    sequences = campaign.get("sequences") if isinstance(campaign, dict) else None
    if not isinstance(sequences, list) or not sequences:
        raise ValueError("campaign_email_sequence_required")

    template_variables: set[str] = set()
    leadscanner_variables: set[str] = set()
    email_step_count = 0
    email_variant_count = 0
    for sequence in sequences:
        if not isinstance(sequence, dict) or not isinstance(sequence.get("steps"), list):
            raise ValueError("campaign_sequence_invalid")
        for step in sequence["steps"]:
            if not isinstance(step, dict):
                raise ValueError("campaign_sequence_invalid")
            if step.get("type") != "email":
                continue
            variants = step.get("variants")
            if not isinstance(variants, list) or not variants:
                raise ValueError("campaign_email_variants_required")
            email_step_count += 1
            for variant in variants:
                if not isinstance(variant, dict):
                    raise ValueError("campaign_email_variant_invalid")
                subject = str(variant.get("subject") or "")
                body = str(variant.get("body") or "")
                if not body.strip():
                    raise ValueError("campaign_email_body_required")
                email_variant_count += 1
                copy = subject + "\n" + body
                matches = VARIABLE_RE.findall(copy)
                # A stray closing brace is as unsafe as an unmatched opening one.
                remainder = VARIABLE_RE.sub("", copy)
                if "{{" in remainder or "}}" in remainder:
                    raise ValueError("campaign_template_syntax_unrecognized")
                for raw_name in matches:
                    name = raw_name.strip()
                    template_variables.add(name)
                    if name.casefold().startswith("leadscanner_"):
                        leadscanner_variables.add(name)

    sequence_fingerprint = hashlib.sha256(
        json.dumps(sequences, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    supported = {
        "leadscanner_lead_id", "leadscanner_review_status",
        "leadscanner_subject", "leadscanner_body",
        "leadscanner_observation", "leadscanner_evidence_url",
        "leadscanner_value_action", "leadscanner_signal_type",
    }
    unsupported = sorted(leadscanner_variables - supported)
    unresolved = sorted(template_variables - leadscanner_variables - GUARANTEED_STANDARD_VARIABLES)
    reviewed_copy_required = bool(
        {"leadscanner_subject", "leadscanner_body"} & leadscanner_variables
    )
    evidence_used = bool(
        {"leadscanner_observation", "leadscanner_value_action"} & leadscanner_variables
    )
    if not email_step_count:
        decision = "no_email_steps"
    elif unsupported:
        decision = "unsupported_leadscanner_fields"
    elif not leadscanner_variables:
        decision = "not_linked_to_leadscanner"
    elif reviewed_copy_required:
        decision = "reviewed_mail_copy_still_required"
    elif unresolved:
        decision = "unresolved_template_fields"
    elif evidence_used:
        decision = "evidence_only_template_candidate"
    else:
        decision = "insufficient_first_party_personalization"

    status = campaign.get("status")
    return {
        "schema_version": "leadscanner-campaign-sequence-audit/1.0",
        "campaign_id": str(campaign.get("id") or "").strip(),
        "campaign_status": status,
        "staging_state_safe": type(status) is int and status in SAFE_CAMPAIGN_STATUSES,
        "sequence_count": len(sequences),
        "sequence_fingerprint": sequence_fingerprint,
        "email_step_count": email_step_count,
        "email_variant_count": email_variant_count,
        "leadscanner_variables": sorted(leadscanner_variables),
        "other_template_variables": sorted(template_variables - leadscanner_variables),
        "unsupported_leadscanner_variables": unsupported,
        "unresolved_template_variables": unresolved,
        "reviewed_copy_required": reviewed_copy_required,
        "first_party_evidence_used": evidence_used,
        "evidence_only_template_candidate": decision == "evidence_only_template_candidate",
        "decision": decision,
    }



def _optional_guarded_evidence_fields(campaign: dict) -> set[str]:
    """Permit optional first-party variables only in their true Liquid branch.

    If the optional value is absent, neither the fallback nor the rest of the
    email may reference it. Match merge fields with Instantly's whitespace
    tolerant syntax; reject nested/unrecognized guards rather than guessing.
    """
    optional = {"leadscanner_observation", "leadscanner_value_action"}
    variable = re.compile(r"\{\{\s*(leadscanner_observation|leadscanner_value_action)\s*\}\}")
    guard = re.compile(
        r"\{%\s*if\s+(?P<cond>leadscanner_observation(?:\s+and\s+leadscanner_value_action)?)\s*%\}"
        r"(?P<yes>.*?)"
        r"(?:\{%\s*else\s*%\}(?P<no>.*?))?"
        r"\{%\s*endif\s*%\}", re.S,
    )
    for sequence in campaign.get("sequences") or []:
        for step in sequence.get("steps") or []:
            for variant in step.get("variants") or []:
                remaining = str(variant.get("subject") or "") + "\n" + str(variant.get("body") or "")
                for block in reversed(list(guard.finditer(remaining))):
                    permitted = set(block.group("cond").split(" and "))
                    true_branch = block.group("yes")
                    false_branch = block.group("no") or ""
                    if "{%" in true_branch or "{%" in false_branch:
                        raise ValueError("campaign_optional_liquid_guard_invalid")
                    if any(match.group(1) not in permitted for match in variable.finditer(true_branch)):
                        raise ValueError("campaign_optional_liquid_guard_invalid")
                    if variable.search(false_branch):
                        raise ValueError("campaign_personalization_variable_missing:optional_evidence_unprotected")
                    remaining = remaining[:block.start()] + remaining[block.end():]
                if variable.search(remaining):
                    raise ValueError("campaign_personalization_variable_missing:optional_evidence_unprotected")
    return optional


def validate_campaign_personalization(
    campaign: dict,
    variables: dict[str, str],
    *,
    review_mode: str = "reviewed_mail",
    sequence_approval: str = "",
) -> None:
    """Require a reviewed three-step Draft sequence before fact-only staging."""
    report = inspect_campaign_sequence(campaign)
    referenced = set(report["leadscanner_variables"])
    if not report["email_variant_count"] or not referenced:
        raise ValueError("campaign_leadscanner_personalization_required")
    # Optional evidence guards are meaningful only for a reviewed-copy template.
    # Keep older missing/unmapped-field failure codes stable for evidence-only ones.
    # Optional verified observation/action may appear in guarded Liquid follow-ups.
    # Legacy imported draft leads have reviewed subject/body but no source fact fields.
    # Every optional merge must be inside its exact guard, never leak as a blank token.
    optional: set[str] = set()
    if review_mode == "reviewed_mail" and {"leadscanner_subject", "leadscanner_body"} <= referenced:
        optional = _optional_guarded_evidence_fields(campaign)
    if any(not variables.get(name) for name in referenced - optional):
        raise ValueError("campaign_personalization_variable_missing")
    if report["unresolved_template_variables"]:
        raise ValueError("campaign_personalization_variable_missing")
    if review_mode == "instantly_sequence":
        if (
            report["sequence_count"] != 1
            or report["email_step_count"] != 3
            or report["decision"] != "evidence_only_template_candidate"
            or not {"leadscanner_observation", "leadscanner_value_action"} <= referenced
            or {"leadscanner_subject", "leadscanner_body"} & referenced
        ):
            raise ValueError("approved_three_step_evidence_sequence_required")
        if report["campaign_status"] != 0 or type(report["campaign_status"]) is not int:
            raise ValueError("sequence_campaign_must_be_draft")
        expected = (
            "APPROVE_INSTANTLY_SEQUENCE "
            + report["campaign_id"] + " " + report["sequence_fingerprint"]
        )
        if sequence_approval != expected:
            raise ValueError("instantly_sequence_approval_fingerprint_mismatch")
    elif review_mode == "reviewed_mail":
        if not {"leadscanner_subject", "leadscanner_body"} <= referenced:
            raise ValueError("reviewed_mail_campaign_must_use_approved_copy")
        if sequence_approval:
            raise ValueError("sequence_approval_not_applicable_to_reviewed_mail")
    else:
        raise ValueError("unsupported_review_mode")



class InstantlyError(RuntimeError):
    pass


class InstantlyClient:
    def __init__(self, api_key: str, *, session=None, timeout: int = 20, base_url: str = BASE_URL, sleep_fn=time.sleep):
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("instantly_api_key_required")
        self.api_key = key
        self.session = session or requests.Session()
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.sleep_fn = sleep_fn

    @staticmethod
    def _retry_delay(response) -> float:
        headers = getattr(response, "headers", {}) or {}
        raw = str(headers.get("Retry-After", "") or "").strip()
        try:
            return min(max(float(raw), 0.0), 5.0)
        except ValueError:
            return 1.0

    def _request(self, method: str, path: str, *, params=None, json=None, retry_safe: bool = False):
        attempts = 2 if retry_safe else 1
        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method,
                    self.base_url + path,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    params=params,
                    json=json,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if retry_safe and attempt + 1 < attempts:
                    self.sleep_fn(1.0)
                    continue
                if not retry_safe and method.upper() in {"POST", "PATCH", "PUT", "DELETE"}:
                    raise InstantlyError("instantly_write_outcome_unknown") from exc
                raise InstantlyError("instantly_network_error") from exc

            if 200 <= response.status_code < 300:
                if response.status_code == 204 or not response.content:
                    return None
                try:
                    return response.json()
                except (TypeError, ValueError) as exc:
                    raise InstantlyError("instantly_invalid_json_response") from exc

            if retry_safe and attempt + 1 < attempts and (
                response.status_code == 429 or response.status_code >= 500
            ):
                self.sleep_fn(self._retry_delay(response))
                continue

            # Campaign creation errors may include private provider context. Only
            # emit a fixed allowlist of schema-key hints, never raw response data.
            if method.upper() == "POST" and path == "/campaigns" and response.status_code == 400:
                try:
                    detail = response.json()
                except (TypeError, ValueError):
                    detail = None
                response_text = str(detail).casefold()[:5000]
                key_names = (
                    "campaign_schedule", "schedules", "schedule", "timezone",
                    "timing", "days", "sequences", "steps", "variants",
                    "name", "email_list", "sender", "stop_on_reply",
                    "permission", "quota", "limit", "account", "plan",
                    "required", "invalid",
                )
                clues = [key for key in key_names if key in response_text]
                safe_suffix = " field_hints=" + ",".join(clues) if clues else " field_hints=none"
                raise InstantlyError(f"instantly_api_error status=400{safe_suffix}")
            raise InstantlyError(f"instantly_api_error status={response.status_code}")

        raise InstantlyError("instantly_request_exhausted")

    def list_campaigns(self, *, limit: int = 50, starting_after: str | None = None, status: int | None = None):
        params = {"limit": min(max(int(limit), 1), 100)}
        if starting_after:
            params["starting_after"] = starting_after
        if status is not None:
            params["status"] = int(status)
        return self._request("GET", "/campaigns", params=params, retry_safe=True)

    def get_campaign(self, campaign_id: str):
        return self._request("GET", f"/campaigns/{quote(str(campaign_id), safe='')}", retry_safe=True)

    def list_leads(
        self,
        *,
        campaign: str | None = None,
        list_id: str | None = None,
        contacts: list[str] | None = None,
        limit: int = 50,
        starting_after: str | None = None,
    ):
        body = {"limit": min(max(int(limit), 1), 100)}
        if campaign:
            body["campaign"] = campaign
        if list_id:
            body["list_id"] = list_id
        normalized_contacts = [
            str(value or "").strip().casefold()
            for value in (contacts or [])
            if str(value or "").strip()
        ]
        if normalized_contacts:
            body["contacts"] = normalized_contacts
        if starting_after:
            body["starting_after"] = starting_after
        return self._request("POST", "/leads/list", json=body, retry_safe=True)

    def get_lead(self, lead_id: str):
        return self._request("GET", f"/leads/{quote(str(lead_id), safe='')}", retry_safe=True)

    def get_emails(
        self,
        *,
        campaign_id: str | None = None,
        received_only: bool = True,
        limit: int = 50,
        starting_after: str | None = None,
    ):
        params = {"limit": min(max(int(limit), 1), 100)}
        if campaign_id:
            params["campaign_id"] = campaign_id
        if received_only:
            params["email_type"] = "received"
        if starting_after:
            params["starting_after"] = starting_after
        return self._request("GET", "/emails", params=params, retry_safe=True)

    def get_campaign_analytics(self, *, campaign_id: str | None = None):
        params = {}
        if campaign_id:
            params["id"] = campaign_id
        return self._request("GET", "/campaigns/analytics", params=params, retry_safe=True)

    def add_approved_lead_to_campaign(
        self,
        *,
        approved_batch: dict,
        lead_id: str,
        campaign_id: str,
        registry_rows: list[dict],
        sequence_approval: str = "",
    ):
        """Add one exact approved lead, but only to a non-sending campaign state."""
        if approved_batch.get("schema_version") != "leadscanner-approved-revalidation/1.0":
            raise ValueError("approved_revalidation_batch_required")
        safety = approved_batch.get("safety") or {}
        if safety.get("automatic_send") is not False:
            raise ValueError("automatic_send_must_be_false")
        if safety.get("dedupe_rechecked_immediately_before_mutation") is not True:
            raise ValueError("live_dedupe_revalidation_required")

        rows = [row for row in (approved_batch.get("rows") or []) if row.get("lead_id") == lead_id]
        if len(rows) != 1:
            raise ValueError("exact_approved_lead_required")
        row = rows[0]
        if not LEAD_ID_RE.fullmatch(str(lead_id or "")):
            raise ValueError("invalid_leadscanner_lead_id")
        review_mode = str(row.get("review_mode") or "reviewed_mail").strip()
        required_status = "sequence_facts_review" if review_mode == "instantly_sequence" else "review_draft"
        if (
            review_mode not in {"instantly_sequence", "reviewed_mail"}
            or row.get("status") != required_status
            or row.get("contact_basis_status") != "review_required"
        ):
            raise ValueError("review_approval_contract_required")
        if review_mode == "instantly_sequence" and not sequence_approval:
            raise ValueError("instantly_sequence_approval_required")
        if row.get("automatic_send") is not False:
            raise ValueError("automatic_send_must_be_false")

        candidate = {
            "company": row.get("company"),
            "official_domain": row.get("official_domain"),
            "website": row.get("website"),
            "email": row.get("email"),
            "lead_id": row.get("lead_id"),
        }
        if match_candidate(candidate, registry_rows):
            raise ValueError("live_dedupe_match_blocks_instantly_mutation")

        campaign = self.get_campaign(campaign_id)
        if not isinstance(campaign, dict) or str(campaign.get("id") or "").strip() != str(campaign_id):
            raise RuntimeError("campaign_readback_id_mismatch")
        campaign_status = campaign.get("status")
        if type(campaign_status) is not int or campaign_status not in SAFE_CAMPAIGN_STATUSES:
            raise ValueError("campaign_must_be_draft_or_paused")

        variables = approved_custom_variables(row)
        validate_campaign_personalization(
            campaign, variables,
            review_mode=review_mode,
            sequence_approval=sequence_approval,
        )
        # Workspace dedupe alone does not cover global Instantly opt-outs.
        # Complete provider read must succeed before a new lead can be staged.
        from myhost_instantly_import import blocked_values
        blocked = blocked_values(self)
        email = str(row.get("email") or "").strip().casefold()
        if email.count("@") != 1:
            raise ValueError("approved_email_required")
        domain = email.rsplit("@", 1)[-1]
        if email in blocked or any(
            "@" not in value and (domain == value or domain.endswith("." + value))
            for value in blocked
        ):
            raise ValueError("provider_blocklist_blocks_stage")
        # A campaign can become Active or change copy while the provider
        # suppression list is being fetched. Re-read immediately before POST.
        current = self.get_campaign(campaign_id)
        safety_fields = (
            "email_list", "sequences", "allow_risky_contacts", "stop_on_reply",
            "stop_on_auto_reply", "stop_for_company", "campaign_schedule",
            "daily_limit", "daily_max_leads", "email_gap",
            "open_tracking", "link_tracking", "text_only", "insert_unsubscribe_header",
        )
        if (
            not isinstance(current, dict)
            or str(current.get("id") or "").strip() != str(campaign_id)
            or type(current.get("status")) is not int
            or current["status"] not in SAFE_CAMPAIGN_STATUSES
            or current.get("status") != campaign_status
            or any(current.get(key) != campaign.get(key) for key in safety_fields)
        ):
            raise ValueError("campaign_changed_during_lead_preflight")
        validate_campaign_personalization(
            current, variables, review_mode=review_mode,
            sequence_approval=sequence_approval,
        )
        payload = {
            "campaign": campaign_id,
            "email": str(row.get("email") or "").strip(),
            "company_name": str(row.get("company") or "").strip(),
            "website": str(row.get("website") or "").strip(),
            "skip_if_in_workspace": True,
            "skip_if_in_campaign": True,
            "custom_variables": variables,
        }
        if not payload["email"]:
            raise ValueError("approved_email_required")
        return self._request("POST", "/leads", json=payload)

    def block_email(self, email: str):
        value = str(email or "").strip().casefold()
        if "@" not in value:
            raise ValueError("valid_email_required")
        return self._request("POST", "/block-lists-entries", json={"bl_value": value})

    def block_domain(self, domain: str):
        value = str(domain or "").strip().casefold().removeprefix("www.")
        if not value or "@" in value or "." not in value:
            raise ValueError("valid_domain_required")
        return self._request("POST", "/block-lists-entries", json={"bl_value": value})


EXPOSED_TOOLS = (
    "list_campaigns",
    "get_campaign",
    "list_leads",
    "get_lead",
    "get_emails",
    "get_campaign_analytics",
    "add_approved_lead_to_campaign",
    "block_email",
    "block_domain",
)

FORBIDDEN_TOOL_NAMES = (
    "activate_campaign",
    "send_email",
    "send_test_email",
    "reply_to_email",
    "forward_email",
    "create_campaign",
    "patch_campaign_sequence",
)
