"""Fail-closed format policy for NEW owner-triggered Mijn.Host draft writes.

Historical 450-review, read-only audits and existing drafts remain untouched.
This module validates structure, not whether a first-party observation is true;
official source proof, suppression and final human/legal review remain separate.
"""
from __future__ import annotations

import re

OPT_OUT = "Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij."
_FORBIDDEN = re.compile(
    r"\b(?:ik kan|ik help|gratis|korting|aanbieding|garantie|"
    r"webactueel|social media|een social voorbeeld|een video|een audit)\b", re.I
)


def validate_short_email(row: dict) -> None:
    """Validate one neutral observation + one gentle question, never send."""
    if not isinstance(row, dict):
        raise RuntimeError("short_email_format_invalid")
    subject = row.get("subject")
    body = row.get("body")
    if not isinstance(subject, str) or not isinstance(body, str):
        raise RuntimeError("short_email_format_invalid")
    if (not 1 <= len(subject.strip()) <= 100
            or subject != subject.strip()
            or any(c in subject for c in "\r\n\0{}[]")
            or _FORBIDDEN.search(subject)):
        raise RuntimeError("short_email_subject_invalid")
    if ("\r" in body or "\0" in body or "{" in body or "}" in body
            or "[" in body or "]" in body or len(body.split()) > 110):
        raise RuntimeError("short_email_format_invalid")
    parts = body.strip().split("\n\n")
    if len(parts) != 5:
        raise RuntimeError("short_email_format_invalid")
    greeting, observation, question, opt_out, sign_off = parts
    if greeting != "Goedendag," or opt_out != OPT_OUT or sign_off != "Groet,\nAndrew":
        raise RuntimeError("short_email_format_invalid")
    if (not observation.startswith("Ik zag dat ")
            or not observation.endswith(".")
            or "\n" in observation or "?" in observation
            or len(observation.split()) < 6 or _FORBIDDEN.search(observation)):
        raise RuntimeError("short_email_observation_invalid")
    if (not question.startswith("Zou het handig zijn als ")
            or not question.endswith("?") or "\n" in question
            or question.count("?") != 1 or len(question.split()) < 7
            or _FORBIDDEN.search(question)):
        raise RuntimeError("short_email_question_invalid")
    if body.count("?") != 2:
        raise RuntimeError("short_email_format_invalid")
