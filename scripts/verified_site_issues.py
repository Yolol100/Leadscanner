"""Conservative source-HTML issue evidence for review-only outreach.

This is not a browser audit or a WCAG conformance claim. Never submit forms,
follow mailto links, or infer defects from missing marketing features.
"""
from html.parser import HTMLParser


class _IssueMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form_depth = 0
        self.label_depth = 0
        self.label_targets = set()
        self.controls = []
        self.links = []
        self._active_link = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        tag = tag.lower()
        if tag == "form":
            self.form_depth += 1
        if tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.label_targets.add(a["for"])
        if self.form_depth and tag in {"input", "select", "textarea"}:
            kind = str(a.get("type") or "text").lower()
            if kind not in {"hidden", "submit", "reset", "button", "image"} and "disabled" not in a:
                named = (bool(str(a.get("aria-label") or "").strip())
                         or bool(str(a.get("aria-labelledby") or "").strip())
                         or bool(str(a.get("title") or "").strip())
                         or self.label_depth > 0)
                self.controls.append((a.get("id"), named))
        if tag == "a":
            self._active_link = {
                "has_img": False,
                "accessible": bool(str(a.get("aria-label") or "").strip()
                                   or str(a.get("aria-labelledby") or "").strip()
                                   or str(a.get("title") or "").strip()),
            }
        if tag == "img" and self._active_link is not None:
            self._active_link["has_img"] = True
            if str(a.get("alt") or "").strip():
                self._active_link["accessible"] = True

    def handle_data(self, data):
        if self._active_link is not None and data.strip():
            self._active_link["accessible"] = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._active_link is not None:
            self.links.append(self._active_link)
            self._active_link = None
        if tag == "label" and self.label_depth:
            self.label_depth -= 1
        if tag == "form" and self.form_depth:
            self.form_depth -= 1


def markup_issues(html: str, source_url: str) -> list[dict]:
    """Only two objectively observable HTML patterns; require human review."""
    parser = _IssueMarkup()
    try:
        parser.feed(html or "")
    except (ValueError, TypeError):
        return []
    issues = []
    if any(not named and (not ident or ident not in parser.label_targets)
           for ident, named in parser.controls):
        issues.append({
            "category": "unlabeled_form_control", "source_type": "official_site",
            "source_url": source_url, "severity": 90,
            "observation_nl": "In het HTML-formulier staat een invoerveld zonder gekoppeld toegankelijk label",
            "observation_en": "An input in the HTML form has no associated accessible label",
        })
    if any(item["has_img"] and not item["accessible"] for item in parser.links):
        issues.append({
            "category": "unnamed_image_link", "source_type": "official_site",
            "source_url": source_url, "severity": 85,
            "observation_nl": "Een afbeeldingslink in de HTML heeft geen tekst of toegankelijke naam",
            "observation_en": "An image link in the HTML has no text or accessible name",
        })
    return issues


def verified_broken_link(source_url: str, target_url: str) -> dict:
    """Caller must independently observe HTTP 404 twice on an internal link."""
    from urllib.parse import urlparse
    target_path = urlparse(target_url).path[:100] or "/"
    return {
        "category": "broken_internal_link", "source_type": "official_site",
        "source_url": source_url, "target_url": target_url, "severity": 100,
        "observation_nl": f"Een interne link naar {target_path} geeft bij twee controles HTTP 404",
        "observation_en": f"An internal link to {target_path} returned HTTP 404 on two checks",
    }
