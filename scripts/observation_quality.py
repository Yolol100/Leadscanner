"""Conservative first-party prose gate. Metadata is never business evidence."""
from __future__ import annotations

import re
from html.parser import HTMLParser


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def observation_rejection(value: str) -> str | None:
    text = clean_text(value)
    if not 3 <= len(text.split()) <= 36 or len(text) > 240:
        return "not_one_short_business_sentence"
    if re.search(r"[|<>\n]|\s[–—]\s|\s-\s|©|https?://|www\.|@", text):
        return "metadata_separator_or_contact_data"
    if re.search(r"\b\d{4}\s?[a-z]{2}\b|\b(?:straat|street|laan|weg|road)\s+\d", text, re.I):
        return "address_fragment"
    if re.search(r"(?:[.!?]\s+\S)|[!?;:]", text):
        return "multiple_sentences_or_non_declarative_fragment"
    if re.search(r"\b(welkom|welcome|copyright|reserved|cookie|privacy|vacature|career|review|klantenservice|contact|reserveringen|nieuwsbrief|newsletter|groet|geholpen|klik|click|beste|best|nummer één|number one|trots|mooiste|krenten|zoek|gehad|vandaag|whatsapp|bereikbaar|beiden|helaas|javascript|trackingtechnologie|browser|website|construction|domain|winkelwagen|voordeel|laagste|gratis|geopend|korting)\b", text, re.I):
        return "boilerplate_contact_review_or_unsubstantiated_claim"
    # Require an explicit subject and finite business predicate. Category,
    # company, address and keyword lists have no such predicate.
    predicate = re.search(r"^(?:Wij|We|Jullie|Our|[A-ZÀ-Ý][\w'’.-]*(?:\s+[\w'’.-]+){0,5})\s+(?:zijn|is|bieden|biedt|verkopen|verkoopt|maken|maakt|serveren|serveert|leveren|levert|produceren|produceert|verhuren|verhuurt|organiseren|organiseert|hebben|heeft|are|offers?|sells?|serves?|provides?|manufactures?|produces?|specializes?|specialises?|rents?|organizes?|organises?)\b", text)
    if re.match(r"^(?:Wij|We|Jullie)\b", text) and not re.match(r"^(?:Wij|We|Jullie) (?:zijn|bieden|verkopen|maken|serveren|leveren|produceren|verhuren|organiseren|hebben|are|offer|sell|serve|provide|manufacture|produce|specialize|specialise|rent|organize|organise)\b", text):
        return "non_business_predicate_or_embedded_fragment"
    if re.search(r"\b(?:en|and|maar|but)\s+(?:(?:wij|we|jullie)\s+)?(?:zijn|is|bieden|biedt|verkopen|verkoopt|maken|maakt|serveren|serveert|leveren|levert|hebben|heeft|offers?|provides?|sells?|serves?)\b", text, re.I):
        return "multiple_business_predicates"
    if re.search(r"\b(?:en|and|maar|but)\s+(?:denken|werken|kunnen|mogen|zullen|willen|doen|gaan|kunt|kijken|betrekken|can|think|work|will|want)\b|,\s*(?:voor|om|zodat|als|we|wij)|\b(?:zodat|omdat|want)\b", text, re.I):
        return "compound_or_complex_business_sentence"
    if re.match(r"^(?:Wij|We|Jullie) (?:zijn|are)\b", text) and not re.search(r"\b(?:gespecialiseerd|specialized|specialised)\b", text):
        return "generic_copula_not_a_concrete_offering"
    if re.match(r"^(?:Wij|We|Jullie) (?:hebben|have)\b", text) and not re.search(r"\b(?:assortiment|collectie|menu|webshop|winkel|terras|vestiging|collection|range|menu|store|terrace)\b", text, re.I):
        return "generic_possession_or_review_not_a_concrete_offering"
    if re.search(r"\b(?:voor ieder wat wils|er iets moois van|maatwerk|gebruik van)\b", text, re.I) and len(text.split()) <= 8:
        return "generic_claim_without_specific_business_fact"
    if re.search(r"[\x80-\x9f]|â|Ã", text):
        return "corrupt_or_undecoded_text"
    if not predicate:
        return "no_explicit_business_subject_and_predicate"
    return None


class ProseParser(HTMLParser):
    """Read visible body blocks; skip metadata, navigation and testimonials."""
    BLOCKS = {"p", "h1", "h2", "h3", "li", "div", "section", "article", "td"}
    VOID = {"meta", "link", "img", "br", "hr", "input", "source", "wbr", "area", "base", "embed", "param", "track", "col"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        markers = " ".join(str(attrs.get(k, "")) for k in ("class", "id", "role", "itemprop"))
        blocked = tag in {"head", "title", "script", "style", "nav", "footer", "header", "aside", "form", "blockquote"} or bool(re.search(r"breadcrumb|footer|copyright|testimonial|review|vacanc|career|cookie", markers, re.I))
        inherited = any(x[1] for x in self.stack)
        if tag not in self.VOID:
            self.stack.append([tag, blocked or inherited, []])

    def handle_data(self, data):
        if any(x[1] for x in self.stack):
            return
        for node in reversed(self.stack):
            if node[0] in self.BLOCKS:
                node[2].append(data)
                break

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                for node in self.stack[i:]:
                    if node[0] in self.BLOCKS and not node[1]:
                        text = clean_text(" ".join(node[2]))
                        if text and text not in self.blocks:
                            self.blocks.append(text)
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
        complement = match[3]
        if verb == "aanbieden":
            complement = re.sub(r"\s+aan$", "", complement)
        complement = re.sub(r"^(?:u|je)\s+", "", complement)
        if verb == "zijn" and match[3].lower().startswith("gespecialiseerd in "):
            return f"Ik zag op jullie website dat jullie gespecialiseerd zijn in {match[3][len("gespecialiseerd in "):]} .".replace(" .", ".")
        return f"Ik zag op jullie website dat jullie {complement} {verb}."
    # A complete verb-bearing sentence quoted as one fact is grammatical;
    # it also retains the site's exact subject, tense and qualifiers.
    return f'Op jullie website las ik: “{text}.”'
