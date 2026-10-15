# Leadscanner: opschonen en sneller brononderzoek (2026-10-15)

## Besluit en grens

**Leadscanner** blijft de uitvoerder voor officiële bedrijfswebsites. `webactueel-workflow` blijft controller; `leads` blijft de vierstappen-specialist. Gebruik rechtstreeks de bedrijfswebsite vanuit de al bekende Overture/PDOK-hint of het privé `Approved`-tabblad. Gebruik niet standaard opnieuw Google Web Search per bedrijf.

De losse repository `Yolol100/browser-search` is géén websiteverificator: hij zoekt via Playwright/Google op een zelfgehoste runner; zoekresultaten zijn alleen hints. Niet integreren in de dagelijkse official-site-controle. Dat scheelt browseropstart, issue-wachttijd en herhaalde zoekstappen. Geen CAPTCHA- of Google-block-omzeiling.

## Wat kan blijven

| Onderdelen | Status/reden |
| --- | --- |
| `fresh-leads.yml`, `overture_discovery.py`, `verified_fill.py` | Actieve zoektocht + zes parallelle officiële websitechecks + maximaal 100 per batch |
| `verify_official_lead.py`, `url_safety.py`, `target_scope.py` | Officiële bedrijfsidentiteit, bedrijfstak, gepubliceerd adres, robots en veilige URL |
| `registry_readonly.py`, `historical_v2.py`, `dedupe_preflight.py` | HMAC/history, opt-outs, terugkerende bedrijven uitsluiten |
| `approved_handoff.py`, `private_candidate_handoff.py` | Alleen geverifieerde contactdata in privé Sheet; exacte readback |
| `draft_queue_readonly.py`, `myhost_draft.py`, `draft_trigger.py`, `myhost-draft.yml` | Eén echte conceptmail + Mijn.Host IMAP-readback, geen SMTP/send |
| Alle bestaande synthetische beveiligings- en regressietests | Beschermen de vierstappenworkflow |
| Bestaande 450-specifieke workflows en scripts | Tijdelijk behouden: de 450-mailtaak loopt aantoonbaar in een andere chat; verwijderen zou haar kunnen breken |

## Opgeschoond/nieuw, zonder mailboxwijzigingen

1. **Nieuw:** `scripts/fast_website_evidence.py` gebruikt maximaal acht gelijktijdige, afzonderlijke HTTP-sessies voor officiële sites. Per site dezelfde bestaande conservatieve verifier (homepage, robots, zo nodig een contact-/over-ons-pagina). **Geen Google-zoekopdrachten, browser of extra API-key.**
2. **Sneller:** `verify_official_site(..., expected_email=...)` hergebruikt de officiële homepage als exact hetzelfde eerder gecontroleerde e-mailadres daar al letterlijk staat. Dit voorkomt de derde HTTP-aanvraag (contactpagina) in dat scenario. De normale nieuwe-leadroute blijft ongewijzigd en geeft een expliciet gepubliceerde contactpersoon prioriteit.
3. **Hergebruik:** cache maximaal 24 uur op basis van identiteits- en branchehash; `--force` dwingt een nieuwe controle af. Een onzekere bron wordt niet als bevestigd gecachet. De extra onderzoeksgegevens komen uitsluitend in een nieuw `WebsiteEvidence`-tabblad van het **bestaande privé Lead Candidates Sheet** na handmatige workflow-activatie. De bestaande `Approved`, `Review450`, geschiedenis en mailbox worden niet veranderd.
4. **Bewijs:** bewaar specifieke, op de website aangetroffen dienstvermeldingen, korte bronpassages, bron-URL, datum en tekstvermeldingen van bestaande opties. Een vermelding van 'online boeken' is **geen bewijs** dat de functie daadwerkelijk werkt; laat dat onderscheiden en controleer ontbrekende functies nooit op basis van afwezigheid van een woord. Bij afwijkend maildomein: `needs_manual_check`.
5. **Batches:** `Approved` = maximaal 100 per batch 1. `Review450` = 5 groepen van maximaal 100, uitsluitend read-only ten aanzien van de lopende andere chat. Elke batch leest de bron vóór en na, stopt bij bronverandering en controleert de exacte privé-write/readback. Logs bevatten alleen aantallen en duur.
6. **Geen auto-integratie:** `fast-website-evidence.yml` is optioneel en handmatig; de 450-herschrijvers en de Draft Queue zijn onaangetast. Green CI bewijst synthetische tests, geen live-mail of echte snelheid bij alle websites.

## Wat niet veilig weg kan (nu)

Er zijn op `main` geen geïdentificeerde losse browser-search/MCP-onderdelen om uit Leadscanner te verwijderen. Eerdere eenmalige mailboxbestanden zijn al afwezig in de actuele main-tree; de nog open concept-PR #1626 over die oude bestanden niet opnieuw uitvoeren. De 450-specifieke scripts zijn nog gekoppeld aan actieve workflows en tests. **Verwijder die uitsluitend na afronding en exacte readback van de andere chat**, in een aparte PR. Ook de afzonderlijke kwaliteits-PR #1688 blijft ongewijzigd; niet stil samenvoegen.

## Gebruik na gecontroleerde merge naar main

Ga naar **Actions → Fast official website evidence - private only → Run workflow**. Kies `Approved`, batch `1`. Voor de historische dataset (zonder inhoudelijke mailwijziging) kies `Review450`, batch `1` t/m `5`. Bekijk vervolgens **het nieuwe privé-tabblad `WebsiteEvidence`** en gebruik alleen regels met `status=verified_with_detail` als bron *voor een zakelijke observatie*; de eventuele aanbod-/functieaanvulling en de wettelijke verzendcontrole blijven aparte menselijke beoordeling.

Bij onbetrouwbare bron: geen mail vrijgeven. Bewaar oude review-/mailboxstatus en herschrijf geen bestaande concepten automatisch.

## Gecontroleerde rollback

Vóór merge: sluit de concept-PR; `main` en alle bestaande private sheets blijven ongewijzigd. Na merge: schakel alleen het nieuwe workflowbestand uit of revert de exacte commits. De nieuwe tab bevat operationele evidence en is geen nieuwe canonieke kennisbank; verwijder dit tabblad niet zonder eerst de andere chat en gebruikerscontext te controleren. Oude `Approved`-/`Review450`-tabbladen en IMAP zijn expliciet buiten scope.
