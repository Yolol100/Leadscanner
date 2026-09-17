from __future__ import annotations

import re

import outreach_copy_v17_2 as base

CONTRACT_ID = base.CONTRACT_ID
POLICY_VERSION = "17.3.0"
CopyDraft = base.CopyDraft

UNSUPPORTED_INFERENCE_PATTERNS = (
    re.compile(r"(?i)\b(?:budget|budgetten)\b[\s\S]{0,60}\b(?:adverteren|advertenties?|ads|google ads)\b"),
    re.compile(r"(?i)\b(?:adverteren|advertenties?|ads|google ads)\b[\s\S]{0,60}\b(?:budget|budgetten)\b"),
    re.compile(r"(?i)\b(?:bedrijf|business|jullie|you)\b[\s\S]{0,45}\b(?:gesloten|closed)\b"),
    re.compile(r"(?i)\bllms\.txt\b[\s\S]{0,140}\b(?:google|search|zoek|ai|visibility|zichtbaar|zichtbaarheid|recommend|aanbevel)\w*\b"),
    re.compile(r"(?i)\b(?:google|search|zoek|ai|visibility|zichtbaar|zichtbaarheid|recommend|aanbevel)\w*\b[\s\S]{0,140}\bllms\.txt\b"),
)

ARTIFACT_EXISTENCE_PATTERNS = (
    re.compile(r"(?i)\bik heb\b[\s\S]{0,80}\b(?:voorbeeld|schets|flow|postplan|uitwerking|mock-?up)\b[\s\S]{0,80}\b(?:gemaakt|uitgewerkt|klaar)\b"),
    re.compile(r"(?i)\bi (?:made|created|prepared)\b[\s\S]{0,80}\b(?:example|sketch|flow|outline|post plan|mock-?up)\b"),
    re.compile(r"(?i)\b(?:het|the)\s+(?:voorbeeld|example)\b[\s\S]{0,30}\b(?:ligt klaar|is ready)\b"),
)


def _extra_errors(text: str, *, artifact_ready: bool, prefix: str) -> list[str]:
    errors: list[str] = []
    if any(pattern.search(text) for pattern in UNSUPPORTED_INFERENCE_PATTERNS):
        errors.append(f"{prefix} contains unsupported inferred claim")
    if not artifact_ready and any(pattern.search(text) for pattern in ARTIFACT_EXISTENCE_PATTERNS):
        errors.append(f"{prefix} claims an example already exists without artifact readback proof")
    return errors


def initial_copy_errors(subject: str, body: str, *, artifact_ready: bool = False) -> list[str]:
    text = str(body or "")
    return base.initial_copy_errors(subject, body) + _extra_errors(
        text, artifact_ready=artifact_ready, prefix="first-touch"
    )


def followup_copy_errors(body: str, *, artifact_ready: bool = False) -> list[str]:
    text = str(body or "")
    return base.followup_copy_errors(body) + _extra_errors(
        text, artifact_ready=artifact_ready, prefix="follow-up"
    )


def _assert_supported(value: str, *, field: str) -> str:
    text = base._clean_fragment(value, field=field)
    if any(pattern.search(text) for pattern in UNSUPPORTED_INFERENCE_PATTERNS):
        raise ValueError(f"{field} contains unsupported inferred claim")
    return text


def build_curiosity_first_copy(
    *,
    company: str,
    language: str,
    subject: str,
    observation: str,
    friction: str,
    example_label: str,
    website: str = "andrewbaeten.nl",
    postal_address: str = "",
    artifact_ready: bool = False,
) -> CopyDraft:
    base._clean_fragment(company, field="company")
    observation = _assert_supported(observation, field="observation")
    friction = _assert_supported(friction, field="friction")
    example_label = base._clean_fragment(example_label, field="example_label")
    lang = str(language or "").strip().lower()
    if lang not in {"nl", "en"}:
        raise ValueError("language must be nl or en")
    subject_errors = base._subject_errors(subject)
    if subject_errors:
        raise ValueError("subject violates curiosity-first contract: " + "; ".join(subject_errors))
    if any(pattern.fullmatch(observation) for pattern in base.GENERIC_OBSERVATION_PATTERNS):
        raise ValueError("observation is too vague to be evidence-bound")

    example_phrase = base._example_phrase(example_label, language=lang)

    if lang == "nl":
        cta = base.CTA_NL[0]
        artifact_sentence = (
            f"Ik heb {example_phrase} uitgewerkt die dit punt concreet maakt."
            if artifact_ready
            else f"Ik kan {example_phrase} maken die dit punt concreet maakt."
        )
        body = (
            "Beste team,\n\n"
            f"{observation}.\n\n"
            f"{friction}.\n\n"
            f"{artifact_sentence}\n\n"
            f"{cta}\n\n"
            f"{base.OPT_OUT_NL}\n\n"
            f"{base.COMMERCIAL_NL}\n\n"
            f"{base.SIGNATURE_NL}\n{website}"
        )
        followup_status = (
            "Het voorbeeld ligt klaar."
            if artifact_ready
            else "Ik kan het korte voorbeeld nog steeds voor jullie maken."
        )
        followup = (
            "Beste team,\n\n"
            f"Ik kom hier nog één keer op terug. {followup_status}\n\n"
            f"{cta}\n\n"
            f"{base.OPT_OUT_NL}\n\n"
            f"{base.SIGNATURE_NL}"
        )
    else:
        cta = base.CTA_EN[0]
        signature = base.SIGNATURE_EN
        if postal_address:
            signature += f"\n{base.POSTAL_PLACEHOLDER}"
        artifact_sentence = (
            f"I made {example_phrase} to make that point concrete."
            if artifact_ready
            else f"I can make {example_phrase} to make that point concrete."
        )
        body = (
            "Hi team,\n\n"
            f"{observation}.\n\n"
            f"{friction}.\n\n"
            f"{artifact_sentence}\n\n"
            f"{cta}\n\n"
            f"{base.OPT_OUT_EN}\n\n"
            f"{base.COMMERCIAL_EN}\n\n"
            f"{signature}\n{website}"
        )
        followup_status = (
            "The example is ready."
            if artifact_ready
            else "I can still make the short example for you."
        )
        followup = (
            "Hi team,\n\n"
            f"Just following up once. {followup_status}\n\n"
            f"{cta}\n\n"
            f"{base.OPT_OUT_EN}\n\n"
            f"{base.SIGNATURE_EN}"
        )

    errors = initial_copy_errors(subject, body, artifact_ready=artifact_ready)
    errors += followup_copy_errors(followup, artifact_ready=artifact_ready)
    if errors:
        raise ValueError("generated copy violates V17.3.0: " + "; ".join(errors))
    return CopyDraft(subject, body, "", followup, 4)
