# Leadscanner: opschonen en sneller brononderzoek (2026-10-15)

> **Status 16 oktober 2026 — archief/instructiecorrectie:** de hieronder beschreven automatische wekelijkse/werkdagelijkse cron en automatische eerste-conceptenfunctie zijn via [PR #1719](https://github.com/Yolol100/Leadscanner/pull/1719) verwijderd. De bestaande vierstappenworkflow werkt uitsluitend op aanvraag met één ChatGPT-controller en GitHub-issue #1720. Read-only: `LEADS_CHAT_V1:CHECK` en `LEADS_CHAT_V1:DRAFTS_AUDIT`. Bestaande zoek- en evidence-routes: `LEADS_CHAT_V2:<MODE>:r-<32hex>` met `HINTS_10/30/50/100`, `EVIDENCE` of `VERIFIED_100` als MODE en een stabiel ID. Geen automatische tijdschema's, geen automatisch verzenden en geen tweede uitvoeringssysteem. Alle latere vermeldingen van *automatisch aan*, *maandag-run* en *planning* in dit document zijn historische ontwerp-/testinformatie, niet operationele instructies. `Review450`, Mijn.Host, HMAC/opt-outs en Cloudflare-vacature-radar niet veranderen.

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

**Historisch, nu uitgeschakeld:** `fresh-leads.yml` verzamelde elke maandag om 06:23 UTC (07:23/08:23 in Nederland) maximaal 100 nieuwe officiële leads, met **hoogstens 240 websitecontroles** per geplande run. De bestaande volledige historische suppressie wordt vóór iedere aanvraag geladen. Een tekort wordt eerlijk als `partial` geregistreerd; zonder één geverifieerde lead blijft het vorige `Approved`-snapshot onaangetast. Geen campagne, nieuw CRM of automatische verzending.

**Historisch, nu uitgeschakeld:** `fast-website-evidence.yml` ververste maandag t/m vrijdag om 07:17 UTC (08:17/09:17 in Nederland) uitsluitend het **bestaande** `Approved`-snapshot, hergebruikt geldige bewijsrecords gedurende 24 uur, en slaat privé bronpassages op. Voor een nieuwe `fill_100`-run worden de officiële homepage en maximaal één relevante contactpagina maar **één keer** aangevraagd en meteen doorgegeven aan `WebsiteEvidence`: geen tweede crawl. Dagelijkse vervolgcontroles blijven bedoeld voor versheid, niet voor dubbel werk.

**Bewijs:** `verify_official_site(..., collect_evidence=True)` geeft uitsluitend bij succesvolle originele verificatie de al geparste pagina's intern terug. `store_preverified_approved` controleert het exact teruggelezen `Approved`-snapshot voor en na de transactie. `inspect_verified` verwerkt alleen dezelfde host, exact gecontroleerde e-mail en branche en onderscheidt concrete dienstvermeldingen van functie-signalen. Nergens worden prospectnamen of mailteksten in publieke GitHub-uitvoer geplaatst.

**Snelheid controleren:** bij normale rechecks rapporteert GitHub uitsluitend het aantal gecontroleerde sites, geldige cachehits, bronstatus, totale tijd en p50/p95 per website in milliseconden. Dit is werkelijke runtime-evidence zodra een live research-run plaatsvindt; synthetische Python-tests zijn geen bewijs van de snelheid van externe sites. De wekelijkse `fill_100`-rapportage bevat aparte ontdek- en verificatieduur.

**Eénmalige controle direct na release:** een `main`-commit met expliciet begin `LEADS_EVIDENCE_ONCE:` mag alleen de bewijsverificatie van `Approved` activeren. Dit verstuurt geen mails en overschrijft geen `Review450`. De gewone automatische schema's zijn van deze eenmalige trigger gescheiden.

**Persoonlijke copy en Mijn.Host:** de automatische onderzoeksroute vult de feitenbron voor latere conceptvoorbereiding. De afzonderlijke Leads-tekstkwaliteit/IMAP-Drafts-flow behoudt de bron-, dedupe-, afmeld-, menselijke/legal-review- en issue-autorisatiepoorten uit de actieve Leads Skill. Deze wijziging **activeert niet** autonoom concepten opslaan in de mailbox, en wijzigt geen van de 450 bestaande mails. Volledig autonome inhoudelijke mailcreatie vergt een apart geautoriseerd bewijs- en kwaliteitscontract; het zou onjuist zijn deze stap als reeds volledig geautomatiseerd te melden.

**Rollback:** schakel eerst beide schema-triggers uit of revert de geverifieerde squash-commit. De oorspronkelijke `Approved`, `Review450`, `LeadHistory`, Draft Queue en Mijn.Host worden niet verwijderd. Eventueel al geregistreerde historische suppressies niet resetten of opschonen. Een fout in één bewijsbatch mag geen ongeverifieerde bron als succes markeren.

## Historische automatische eerste concepten voor uitsluitend NIEUWE leads (nu uitgeschakeld)

In de oude opzet volgde na een geplande maandag-run de afzonderlijke `auto_first_drafts`-job. Deze geplande route is inmiddels verwijderd en mag niet opnieuw worden aangezet. Nieuwe concepten vereisen nu de bestaande, afzonderlijk eigenaargeautoriseerde handmatige Draft Queue/issue #1659-route met volledige uitsluitingscheck. Het normale klantenproces blijft: bedrijf vinden → officieel zakelijk e-mailadres → concept in Mijn.Host Drafts → menselijke eindcontrole. **Verzenden gebeurt nooit automatisch.**

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

## Afsluiting historische 450-redactie en bronblokkades (15 oktober 2026)

De redactieronde over de 450 historische Mijn.Host-concepten wordt **uitsluitend in de bestaande privé-Google Sheet** beoordeeld. De vijf tabbladen `Batch1Topkwaliteit` t/m `Batch5Topkwaliteit` zijn de primaire redactionele snapshots. `QA450Actueel` is een dynamische, alleen-afgeleide samenvoeging van die vijf tabbladen; `QA450Openstaand` toont uitsluitend rijen waarvan de redactionele status `NIET_VERSTUREN` bevat. `Verbeter450Fases` bevat de actuele aggregaten en de leeswijzer.

De oudere tabbladen `QA450PerMail` en `QA450Batches` zijn **historische nulmetingen**. Gebruik hun eerdere scores en aantallen niet als actuele eindcontrole. Een correcte blokkadetelling gebruikt de gemeenschappelijke statusmarkering `NIET_VERSTUREN`, niet één exacte statusstring. Een niet-geblokkeerde mail is slechts **voor menselijke eindcontrole**: dat is geen toestemming om ongevraagde commerciële e-mail te versturen of de bestaande Mijn.Host-concepten te vervangen.

Het verschil tussen de 450 oorspronkelijke `Review450`-onderwerpen/teksten en de vijf redactionele snapshots moet per origineel concept-ID worden geverifieerd. Het aantal 'nieuwe versies' mag niet worden afgeleid uit aantallen revisies in één chatronde. Bij bronfouten, onjuiste branche, stopzetting of onduidelijke identiteit blijft de betreffende mail geblokkeerd totdat de officiële bron exact is bevestigd; automatische unblock, verwijderen van opt-outs en een mailboxinstallatie zijn verboden.

Dit is een documentatie-/bronrouteringscorrectie, geen nieuwe verzendmogelijkheid. De historische 450-reviewtools en het eenmalige `replace450`-pad blijven uitgeschakeld voor deze redactieronde, tenzij hiervoor later **afzonderlijk** een expliciet geautoriseerde en volledig geteste mailboxopdracht wordt gegeven. De publieke repository bevat geen prospectnamen, adressen of mailteksten.

## Harde bevindingen en hertest — 15 oktober 2026 (vervolg)

De live nulmeting op de privé `Approved`-bron bevatte 57 bedrijven: 27 HTTPS en **30 legitiem officieel geverifieerde HTTP-URL's**. De conceptselectie had een onbedoelde uitsluitend-HTTPS-filter; de gedeelde bronverificateur accepteerde beide protocollen al, met publieke URL-, DNS-, robots-, identiteit- en e-mailcontroles. `auto_draft_new._host` accepteert daarom nu HTTP én HTTPS uitsluitend na de bestaande officiële bronpoorten, zonder gebruikersnaam, wachtwoord, afwijkende poort, onveilig schema of ongetoetst e-mailadres te accepteren. Deze wijziging schakelt geen beveiligingscontrole uit.

De oorspronkelijke 57 bedrijven kwamen uit restaurants (29), logiesbedrijven (14), horecazaken (8) en sportscholen (6). `WebsiteEvidence` had aanvankelijk alleen restaurantspecifieke `DETAILS`. Daarom zijn concrete, **letterlijk op de officiële website te bewijzen** diensten toegevoegd voor logies/horeca/sportscholen en elektrische fietsen. Een branchelabel alleen blijft onvoldoende; onbekende of ontkende feitvermeldingen leiden nooit tot een automatische mail.

Om hervatten te beveiligen bevat de bestaande technische vijfde kolom `quality_status` nu een interne SHA-256 van de **exact opgeslagen Draft Queue-rij** naast de statusprefix. Dat is géén score. Een inhoudelijk gewijzigde rij wordt bij opnieuw proberen geblokkeerd voordat IMAP opent. De oorspronkelijke wachtrij, bestaande 450 en historische opt-outs veranderen niet.

Voor snelheid gebruiken de automatische first-draft- en metadata-checkjobs nu `requirements-draft.txt` (alleen Requests en Google Auth), zonder `overturemaps` en het zware Arrow-ecosysteem. Het afzonderlijke website-evidence-onderzoek gebruikt dezelfde minimale dependencies. Overture blijft behouden waar het nodig is: bedrijfszoektocht en verificatiediscovery.

**Onafhankelijke live QA zonder mailboxwrites:** `auto_draft_new.py --audit-existing` leest alleen de huidige privé `Approved` en `WebsiteEvidence` om geanonimiseerde aantallen (feitelijke detailstatus, actuele geschikte copykandidaten, HTTP-deel) te rapporteren; dit zijn inhoudelijke kandidaten **vóór deduplicatie, menselijke redactie en juridische controle**, geen goedgekeurde leads of verstuurde e-mails. De eenmalige `LEADS_EVIDENCE_ONCE:`-canary ververst de bestaande bewijsbron geforceerd en draait deze audit; `LEADS_CACHE_SMOKE:` controleert daarna cachehergebruik zonder geforceerde webverzoeken. De reguliere week-/werkdagschema's blijven ongewijzigd en verzenden nooit e-mail.

Bij operationele fouten gelden bestaande grenzen: alleen privé technische state repareren, bestaande Draft Queue/Review450 intact laten, geen HMAC/opt-out reset, geen SMTP. Een groene CI blijft alleen codebewijs; echte bron- en IMAP-readback blijven afzonderlijke gates. Bewaar bij afronding de run-ID's en exacte uitkomst.

## Volledige live website-hertest 16 oktober 2026: acceptatie en accountfouten

De geforceerde privé-websitecontrole https://github.com/Yolol100/Leadscanner/actions/runs/38925538404 rapporteerde: requested 57, website_checks 57, reused_recent 0, verified 49, needs_manual_check 8, emails_sent 0, mailbox_writes 0. Het bestaande privé-tabblad WebsiteEvidence is exact teruggelezen: 57 regels passen bij 57 Approved-identiteiten; geen dubbele record_keys of ongeldige facts_json. De acht uitzonderingen zijn niet automatisch acht softwarefouten: twee afwijkende e-maildomeinen, twee onvoldoende lokaliteitsbewijzen en vier gevallen zonder actuele bevestiging van officiële bedrijfsgegevens/e-mailadres. Acceptatie van een geforceerde volledige run vereist website_checks == requested, reused_recent == 0 én correcte private readback, niet alleen groen GitHub CI.

De eerdere run https://github.com/Yolol100/Leadscanner/actions/runs/38914183790 mislukte vóór een websiteverzoek met Google OAuth invalid_grant / account not found. Een nieuw serviceaccount, veilige GitHub Secret en beperkte Google Sheets-deelrechten hebben de inlogroute hersteld. Bij toekomstige Google-authenticatiefouten logt de commandline alleen een anonieme blokkadestatus en stopt met exitcode 2; nooit de providerfout of accountgegevens tonen.

De optionele Cloudflare Browser Run /content-proeven leverden bij één site bruikbare locatie- en dienstsignalen op en bij een andere site ondanks HTTP 200 onvoldoende bruikbare bewijsgegevens. Alleen op verzoek mag een operator een toegestane, read-only vergelijking per needs_manual_check-uitzondering uitvoeren; respecteer robots-/toegangsbeperkingen en pas geen CAPTCHA/403-omzeiling toe. Een HTTP 200, browserpagina of vermelding is geen onafhankelijke bevestiging van een zakelijk e-mailadres of toestemming voor outreach. Zonder bewezen herhaalde meerwaarde geen Worker, extra Cron, KV, Queue, D1 of koppeling met de bestaande vacature-radar.

Dit zijn interne bewijs- en QA-regels onder dezelfde vier Leads-stappen; historische 450, suppressies, privé-concepten, automatische verzending en andere systemen blijven onaangetast.
