"""Conservative first-party prose gate. Metadata is never business evidence."""
from __future__ import annotations

import re
from html.parser import HTMLParser


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def observation_rejection(value: str) -> str | None:
    text = clean_text(value)
    if not 4 <= len(text.split()) <= 36 or len(text) > 240:
        return "not_one_short_business_sentence"
    if re.search(r"[|<>\n]|\s[–—]\s|\s-\s|©|https?://|www\.|@", text):
        return "metadata_separator_or_contact_data"
    if re.search(r"\b\d{4}\s?[a-z]{2}\b|\b(?:straat|street|laan|weg|road)\s+\d", text, re.I):
        return "address_fragment"
    if re.search(r"(?:[.!?]\s+\S)|[!?;:]", text):
        return "multiple_sentences_or_non_declarative_fragment"
    if re.search(r"\b(welkom|welcome|copyright|reserved|cookie|privacy|vacature|career|review|klantenservice|contact|reserveringen|nieuwsbrief|newsletter|groet|geholpen|klik|click|beste|best|nummer één|number one)\b", text, re.I):
        return "boilerplate_contact_review_or_unsubstantiated_claim"
    # Require an explicit subject and finite business predicate. Category,
    # company, address and keyword lists have no such predicate.
    predicate = re.search(r"\b(?:wij|we|jullie|our|[A-ZÀ-Ý][\w'’.-]*(?:\s+[\w'’.-]+){0,5})\s+(?:zijn|is|bieden|biedt|verkopen|verkoopt|maken|maakt|serveren|serveert|leveren|levert|produceren|produceert|verhuren|verhuurt|organiseren|organiseert|hebben|heeft|are|offers?|sells?|serves?|provides?|manufactures?|produces?|specializes?|specialises?|rents?|organizes?|organises?)\b", text)
    if re.search(r"\b(?:en|and|maar|but)\s+(?:(?:wij|we|jullie)\s+)?(?:zijn|is|bieden|biedt|verkopen|verkoopt|maken|maakt|serveren|serveert|leveren|levert|hebben|heeft|offers?|provides?|sells?|serves?)\b", text, re.I):
        return "multiple_business_predicates"
    if not predicate:
        return "no_explicit_business_subject_and_predicate"
    return None


class ProseParser(HTMLParser):
    """Keep body paragraphs/headings outside navigation/footer/testimonials."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.blocks = []
        self.active = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        markers = " ".join(str(attrs.get(k, "")) for k in ("class", "id", "role", "itemprop"))
        blocked = tag in {"head", "title", "script", "style", "nav", "footer", "header", "aside", "form", "blockquote"} or bool(re.search(r"breadcrumb|footer|copyright|testimonial|review|vacanc|career|cookie", markers, re.I))
        inherited = any(x[1] for x in self.stack)
        if tag not in {"meta", "link", "img", "br", "hr", "input", "source", "wbr"}:
            self.stack.append((tag, blocked or inherited))
        if tag in {"p", "h1", "h2", "h3", "li"} and not (blocked or inherited):
            self.active = tag
            self.parts = []

    def handle_data(self, data):
        if self.active and not any(x[1] for x in self.stack):
            self.parts.append(data)

    def handle_endtag(self, tag):
        if self.active == tag:
            text = clean_text(" ".join(self.parts))
            if text:
                self.blocks.append(text)
            self.active = None
            self.parts = []
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def first_party_prose(html: str) -> list[str]:
    parser = ProseParser()
    parser.feed(html or "")
    return parser.blocks


def business_sentences(html: str) -> list[str]:
    found = []
    for block in first_party_prose(html):
        for sentence in re.split(r"(?<=[.!?])\s+", block):
            sentence = clean_text(sentence)
            if not observation_rejection(sentence) and sentence not in found:
                found.append(sentence)
    return found


def natural_opening(observation: str, language: str) -> str:
    text = clean_text(observation).rstrip(".")
    reason = observation_rejection(text)
    if reason:
        raise ValueError("No specific verified site detail: " + reason)
    if language == "en":
        text = re.sub(r"^(?:We|Our company)\b", "you", text)
        return "I saw on your website that " + text + "."
    # Only move the finite verb for a simple, single-clause statement. All
    # other grammatical prose stays a direct quotation; never infer a category.
    match = re.fullmatch(r"(Wij|We|Jullie) (zijn|bieden|verkopen|maken|serveren|leveren|produceren|verhuren|organiseren|hebben) (.+)", text, re.I)
    if match and not re.search(r"\b(wij|we|onze|ons|maar|omdat|zodat|die|dat)\b|,", match[3], re.I):
        verb = {"bieden": "aanbieden"}.get(match[2].lower(), match[2].lower())
        return f"Ik zag op jullie website dat jullie {match[3]} {verb}."
    # A complete verb-bearing sentence quoted as one fact is grammatical;
    # it also retains the site's exact subject, tense and qualifiers.
    return f'Op jullie website las ik: “{text}.”'
