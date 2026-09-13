from __future__ import annotations

import outreach_daily_batch_drafts as core
import outreach_daily_batch_drafts_v2 as v2
from outreach_agent_prepare_v16 import COPY_CONTRACT, qualification_evidence_ok

_ORIGINAL_DRAFT_QUALIFICATION_OK = v2._draft_qualification_ok
_ORIGINAL_HARDENED_CANDIDATE_ERRORS = v2.hardened_candidate_errors


def _draft_qualification_ok(candidate, qualification) -> bool:
    return qualification_evidence_ok(candidate, qualification)


def hardened_candidate_errors(
    queue_row, *, agent_type: str, country: str, candidate, qualification, contact,
    source, lead_statuses, suppressed_emails, suppressed_domains,
):
    errors = _ORIGINAL_HARDENED_CANDIDATE_ERRORS(
        queue_row,
        agent_type=agent_type,
        country=country,
        candidate=candidate,
        qualification=qualification,
        contact=contact,
        source=source,
        lead_statuses=lead_statuses,
        suppressed_emails=suppressed_emails,
        suppressed_domains=suppressed_domains,
    )
    evidence_ok = bool(candidate and qualification and qualification_evidence_ok(candidate, qualification, agent_type=agent_type))
    meta = core._parse_meta(queue_row.get("source"))
    current_copy = bool(meta and core._text(meta.get("copy_contract")) == COPY_CONTRACT)

    if evidence_ok:
        removable = {
            "candidate is not qualified",
            "qualification status is not qualified",
            "qualification tier is not A",
            "customer potential is below A threshold",
            "queue metadata does not prove A-tier qualification",
        }
        errors = [item for item in errors if item not in removable]
    if not current_copy:
        errors.append("queue copy contract is not current v16")
    return errors


def process(*, target: int, agent_type: str, country: str, run_key: str, count_only: bool = False) -> int:
    old_qualification = v2._draft_qualification_ok
    old_errors = v2.hardened_candidate_errors
    v2._draft_qualification_ok = _draft_qualification_ok
    v2.hardened_candidate_errors = hardened_candidate_errors
    try:
        return v2.process(
            target=target,
            agent_type=agent_type,
            country=country,
            run_key=run_key,
            count_only=count_only,
        )
    finally:
        v2._draft_qualification_ok = old_qualification
        v2.hardened_candidate_errors = old_errors


def main(argv=None) -> int:
    parser = v2.argparse.ArgumentParser(description="Create source-aligned v16 mijn.host drafts without SMTP send permission.")
    parser.add_argument("--target", type=int, default=100)
    parser.add_argument("--agent-type", default="auto")
    parser.add_argument("--country", required=True)
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--count-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        return process(
            target=args.target,
            agent_type=args.agent_type.strip().casefold(),
            country=args.country.strip(),
            run_key=args.run_key.strip(),
            count_only=args.count_only,
        )
    except (RuntimeError, ValueError, OSError, core.imaplib.IMAP4.error) as exc:
        core._write_json("daily-draft-error.json", {
            "status": "blocked", "error": str(exc), "send_permission": "none", "smtp_send": "not_invoked",
        })
        print(f"DAILY_LEAD_DRAFTS=blocked detail={exc} smtp_send=not_invoked", file=core.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
