"""Validate officially published business contact formats for research only."""
import re
EMAIL_LOCAL_RE = re.compile(r"^[a-z0-9._%+\\-]+$", re.I)
EMAIL_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
def valid_general_email(value: str) -> bool:
    """Preserve previous ASCII format check; no mailbox access."""
    if not isinstance(value, str) or not 3 <= len(value) <= 254 or value.count("@") != 1:
        return False
    local, host = value.split("@")
    if (not 1 <= len(local) <= 64 or local.startswith(".") or local.endswith(".")
            or ".." in local or not EMAIL_LOCAL_RE.fullmatch(local)):
        return False
    labels = host.split(".")
    if (len(labels) < 2 or len(host) > 253 or not 2 <= len(labels[-1]) <= 63
            or not all(EMAIL_LABEL_RE.fullmatch(label) for label in labels)):
        return False
    return labels[-1].isalpha() or labels[-1].startswith("xn--")
