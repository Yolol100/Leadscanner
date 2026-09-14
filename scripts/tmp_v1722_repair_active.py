from __future__ import annotations

import json
import os
import re
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build

sys.path.insert(0, "scripts")
from outreach_copy_v17_2 import POLICY_VERSION, initial_copy_errors
from outreach_queue_imap_draft import QUEUE_SHEET, get_values, rows_from_values

TARGET_ROWS = (
    list(range(70, 81))
    + list(range(82, 102))
    + list(range(103, 115))
    + list(range(116, 122))
    + [123, 133, 143]
    + list(range(145, 150))
    + [152]
    + list(range(197, 237))
)
assert len(TARGET_ROWS) == 98 and len(set(TARGET_ROWS)) == 98


def build_write_sheets_service():
    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", str(body or "").strip()) if p.strip()]


def clean(value: str) -> str:
    return " ".join(str(value or "").strip().split()).rstrip(".!?")


def source_meta(value: str) -> dict:
    text = str(value or "")
    try:
        return json.loads(text.split(":", 1)[1] if ":" in text else text)
    except Exception:
        return {}


def main() -> int:
    spreadsheet_id = os.environ["OUTREACH_SPREADSHEET_ID"]
    service = build_write_sheets_service()
    queue_rows = rows_from_values(get_values(service, spreadsheet_id, QUEUE_SHEET))
    by_row = {idx: row for idx, row in enumerate(queue_rows, start=2)}
    missing = [row for row in TARGET_ROWS if row not in by_row]
    if missing:
        raise SystemExit("missing target rows: " + ",".join(map(str, missing)))

    observation_overrides = {
        71: "I noticed that your Request a Quote or Sample route asks for contact details, application and part description"
    }
    backup: list[dict] = []
    updates: list[dict] = []
    selected_ids: list[str] = []

    for sheet_row in TARGET_ROWS:
        row = by_row[sheet_row]
        lead_id = str(row.get("lead_id") or "").strip()
        if not lead_id:
            raise SystemExit(f"row {sheet_row}: missing lead_id")
        status = str(row.get("status") or "").strip().lower()
        compliance = str(row.get("compliance_status") or "").strip().lower()
        verification = str(row.get("verification_status") or "").strip().lower()
        last_error = str(row.get("last_error") or "")
        if status not in {"prepared", "manual_review"}:
            raise SystemExit(f"{lead_id}: ineligible status {status}")
        if compliance not in {"prepared", "manual_review", "approved"}:
            raise SystemExit(f"{lead_id}: ineligible compliance {compliance}")
        if verification not in {"official_site_ready", "manual_web_verified"}:
            raise SystemExit(f"{lead_id}: evidence needs reverification ({verification})")
        if "delivery status notification" in last_error.lower():
            raise SystemExit(f"{lead_id}: bounced lead must stay excluded")

        company = clean(row.get("company"))
        subject = str(row.get("subject") or "").strip()
        old_body = str(row.get("body") or "")
        parts = paragraphs(old_body)
        if len(parts) < 2:
            raise SystemExit(f"{lead_id}: no evidence paragraph in current queue copy")
        observation = clean(observation_overrides.get(sheet_row) or parts[1])
        if len(observation) < 30:
            raise SystemExit(f"{lead_id}: evidence observation is too weak")
        meta = source_meta(row.get("source"))
        offer_type = str(meta.get("agent_type") or meta.get("offer_type") or "")
        lang = "nl" if old_body.lstrip().startswith(("Beste", "Hoi", "Geachte")) or "Geen interesse" in old_body else "en"
        greeting = old_body.split("\n", 1)[0].strip() or ("Beste team," if lang == "nl" else "Hi team,")

        if lang == "nl":
            label = "voorbeeld" if offer_type == "commerce" else "mini-flow"
            body = (
                f"{greeting}\n\n{observation}.\n\n"
                "Daar zit één punt dat ik zelf serieus zou laten checken, omdat het precies op een belangrijk moment in dit proces zit en mogelijk onnodige frictie geeft.\n\n"
                f"Ik heb voor {company} één klein {label} gemaakt dat de mogelijke verbetering concreet maakt.\n\n"
                "Zal ik het voorbeeld sturen?\n\n"
                'Geen interesse? Een kort "nee" is genoeg.\n\n'
                "Dit is een commercieel bericht.\n\n"
                "Met vriendelijke groet,\nAndrew Baeten\nandrewbaeten.nl"
            )
        else:
            label = "sketch" if offer_type == "commerce" else "mini-flow"
            body = (
                f"{greeting}\n\n{observation}.\n\n"
                "One point there is worth checking because it sits at an important moment in that process and may be creating avoidable friction.\n\n"
                f"I made one small {label} for {company} that makes the possible improvement concrete.\n\n"
                "Want me to send the example?\n\n"
                'Not interested? A quick "no" is enough.\n\n'
                "This is a commercial message.\n\n"
                "Best regards,\nAndrew Baeten\n{{OUTREACH_POSTAL_ADDRESS}}\nandrewbaeten.nl"
            )

        errors = initial_copy_errors(subject, body)
        if errors:
            raise SystemExit(f"{lead_id}: generated body failed V17.2.2 copy gate: {errors}")
        selected_ids.append(lead_id)
        backup.append({"lead_id": lead_id, "row": sheet_row, "old_body": old_body, "new_body": body})
        updates.append({"range": f"'{QUEUE_SHEET}'!G{sheet_row}", "values": [[body]]})

    if len(selected_ids) != 98 or len(set(selected_ids)) != 98:
        raise SystemExit("selected active lead cohort is not exactly 98 unique leads")

    with open("selected-lead-ids.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(selected_ids) + "\n")
    with open("v1722-body-repair-backup.json", "w", encoding="utf-8") as fh:
        json.dump({"policy_version": POLICY_VERSION, "count": len(backup), "rows": backup}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    def write(data: list[dict]):
        return service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()

    def readback() -> list[str]:
        ranges = [f"'{QUEUE_SHEET}'!G{x['row']}" for x in backup]
        out = service.spreadsheets().values().batchGet(spreadsheetId=spreadsheet_id, ranges=ranges).execute()
        values: list[str] = []
        for vr in out.get("valueRanges", []):
            rv = vr.get("values") or []
            values.append(str(rv[0][0]) if rv and rv[0] else "")
        return values

    wrote = False
    try:
        write(updates)
        wrote = True
        actual = readback()
        if len(actual) != len(backup):
            raise RuntimeError(f"readback count {len(actual)} != {len(backup)}")
        failures: list[str] = []
        for item, value in zip(backup, actual):
            row = by_row[item["row"]]
            subject = str(row.get("subject") or "").strip()
            if value != item["new_body"] or initial_copy_errors(subject, value):
                failures.append(item["lead_id"])
        if failures:
            raise RuntimeError("exact readback/copy validation failed: " + ",".join(failures))
    except Exception:
        if wrote:
            rollback = [
                {"range": f"'{QUEUE_SHEET}'!G{x['row']}", "values": [[x["old_body"]]]}
                for x in backup
            ]
            write(rollback)
            restored = readback()
            if len(restored) != len(backup) or any(v != x["old_body"] for x, v in zip(backup, restored)):
                raise RuntimeError("repair failed and rollback readback failed")
        raise

    result = {
        "status": "green",
        "policy_version": POLICY_VERSION,
        "target": 98,
        "updated": 98,
        "readback": 98,
        "smtp_send": "not_invoked",
    }
    with open("v1722-body-repair-result.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
        fh.write("\n")
    print("V1722_QUEUE_BODY_REPAIR=green target=98 updated=98 readback=98 smtp_send=not_invoked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
