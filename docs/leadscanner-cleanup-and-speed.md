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

## Upgrade 15 oktober 2026: automatisch, één websitepass en betrouwbare snelheid

**Automatisch aan:** `fresh-leads.yml` verzamelt elke maandag om 06:23 UTC (07:23/08:23 in Nederland) maximaal 100 nieuwe officiële leads, met **hoogstens 240 websitecontroles** per geplande run. De bestaande volledige historische suppressie wordt vóór iedere aanvraag geladen. Een tekort wordt eerlijk als `partial` geregistreerd; zonder één geverifieerde lead blijft het vorige `Approved`-snapshot onaangetast. Geen campagne, nieuw CRM of automatische verzending.

**Automatisch bronhergebruik:** `fast-website-evidence.yml` ververst maandag t/m vrijdag om 07:17 UTC (08:17/09:17 in Nederland) uitsluitend het **bestaande** `Approved`-snapshot, hergebruikt geldige bewijsrecords gedurende 24 uur, en slaat privé bronpassages op. Voor een nieuwe `fill_100`-run worden de officiële homepage en maximaal één relevante contactpagina maar **één keer** aangevraagd en meteen doorgegeven aan `WebsiteEvidence`: geen tweede crawl. Dagelijkse vervolgcontroles blijven bedoeld voor versheid, niet voor dubbel werk.

**Bewijs:** `verify_official_site(..., collect_evidence=True)` geeft uitsluitend bij succesvolle originele verificatie de al geparste pagina's intern terug. `store_preverified_approved` controleert het exact teruggelezen `Approved`-snapshot voor en na de transactie. `inspect_verified` verwerkt alleen dezelfde host, exact gecontroleerde e-mail en branche en onderscheidt concrete dienstvermeldingen van functie-signalen. Nergens worden prospectnamen of mailteksten in publieke GitHub-uitvoer geplaatst.

**Snelheid controleren:** bij normale rechecks rapporteert GitHub uitsluitend het aantal gecontroleerde sites, geldige cachehits, bronstatus, totale tijd en p50/p95 per website in milliseconden. Dit is werkelijke runtime-evidence zodra een live research-run plaatsvindt; synthetische Python-tests zijn geen bewijs van de snelheid van externe sites. De wekelijkse `fill_100`-rapportage bevat aparte ontdek- en verificatieduur.

**Eénmalige controle direct na release:** een `main`-commit met expliciet begin `LEADS_EVIDENCE_ONCE:` mag alleen de bewijsverificatie van `Approved` activeren. Dit verstuurt geen mails en overschrijft geen `Review450`. De gewone automatische schema's zijn van deze eenmalige trigger gescheiden.

**Persoonlijke copy en Mijn.Host:** de automatische onderzoeksroute vult de feitenbron voor latere conceptvoorbereiding. De afzonderlijke Leads-tekstkwaliteit/IMAP-Drafts-flow behoudt de bron-, dedupe-, afmeld-, menselijke/legal-review- en issue-autorisatiepoorten uit de actieve Leads Skill. Deze wijziging **activeert niet** autonoom concepten opslaan in de mailbox, en wijzigt geen van de 450 bestaande mails. Volledig autonome inhoudelijke mailcreatie vergt een apart geautoriseerd bewijs- en kwaliteitscontract; het zou onjuist zijn deze stap als reeds volledig geautomatiseerd te melden.

**Rollback:** schakel eerst beide schema-triggers uit of revert de geverifieerde squash-commit. De oorspronkelijke `Approved`, `Review450`, `LeadHistory`, Draft Queue en Mijn.Host worden niet verwijderd. Eventueel al geregistreerde historische suppressies niet resetten of opschonen. Een fout in één bewijsbatch mag geen ongeverifieerde bron als succes markeren.

## Automatische eerste concepten voor uitsluitend NIEUWE leads

Na de geplande maandag-run volgt in `fresh-leads.yml` de afzonderlijke `auto_first_drafts`-job. Er is geen menselijke startknop meer nodig voor nieuwe, aantoonbaar geschikte leads. Het normale klantenproces blijft: bedrijf vinden → officieel zakelijk e-mailadres → concept in Mijn.Host Drafts → menselijke eindcontrole. **Verzenden gebeurt nooit automatisch.**

Harde selectie in `scripts/auto_draft_new.py`:

- Alleen records uit het huidige `GITHUB_RUN_ID` in het privé `Approved`-snapshot, met `verified_website_and_email` en exact bijbehorende `LeadHistory`; geen herverwerking van de bestaande 57 of de historische 450
- Alleen `WebsiteEvidence` met `verified_with_detail`, overeenkomende bron-/identiteitshash, minder dan 24 uur oude officiële bronpassage, bevestigde branche en direct gekoppeld zakelijk adres op hetzelfde domein
- Alleen concrete diensttermen uit de expliciet onderhouden branchelijst. Een algemene branchevermelding of tekst met ontkenning wordt geblokkeerd. Niets wordt afgeleid uit afwezigheid van een knop/functie
- Maximaal **25 nieuwe eerste concepten per geplande run** (veiligheidslimiet tijdens uitrol); zes vaste branchegerichte invalshoeken met één echte observatie, één bescheiden inhoudelijk voorbeeld, één CTA, verplichte afmelding en korte Andrew-afsluiting. Geen verzonnen resultaten, overname van bestaande boekingsfuncties of auto-marketing-score
- Historische HMAC-suppressie én bestaande privé Draft Queue verhinderen dubbele adressen, bedrijven en domeinen. De canonieke historische `LeadHistory` wordt niet opgeschoond of gereset
- Nieuwe `AutoDraftState` is een **technisch idempotentie-tabblad** in de bestaande privé Draft Queue, geen CRM of kennisbank. Toevoegen van DraftQueue-rijen en bijbehorende willekeurige opaque IDs gebeurt in één Sheets-transactie, gevolgd door exacte readback
- Het bestaande `myhost_draft.create_batch_from_queue` gebruikt één IMAP-sessie en controleert per concept de `\\Draft`-flag en exacte inhoud. Bij herhaalde workflow-run worden bestaande IDs hergebruikt; **geen SMTP, verzending, nieuwsbrieven, tracking of follow-up**

De vorige 450-mailchat en alle bestaande mailboxconcepten vallen expliciet buiten scope. De tekst is een eerste concept, **geen 10/10-garantie**; afzonderlijke menselijke redactie, toestemming, doelgroep- en wettelijke beoordeling blijven vereist. Bij onvoldoende uniek bronbewijs volgt geen automatisch concept. Alleen geanonimiseerde aantallen mogen in GitHub-logs verschijnen.

**Runtimebewijs:** de afzonderlijke onderzoeksfunctie controleerde op 15 oktober 2026 57 officiële websites in 26,95 seconden: 46 geslaagde broncontroles, 11 handmatige controles; 10 specifieke dienstvermeldingen. De geplande nieuwe-conceptenworkflow is synthetisch getest, maar een daadwerkelijke geplande IMAP-run is nog niet uitgevoerd. Groene CI bewijst géén succesvolle echte toekomstige mailboxopslag.

**Herstel:** GitHub Actions → `fresh-leads.yml` uitschakelen of revert van de merge schakelt zowel wekelijkse nieuwe-leadverzameling als nieuwe automatische Drafts uit. Schakel desgewenst alleen `auto_first_drafts` uit via een rollback-commit om onderzoek te behouden. Oude `Review450` en Mijn.Host-gegevens nooit wissen. Handmatige IMAP-/kwaliteitscontrole blijft eindpoort.
