# Leadscanner — onafhankelijke gap-only heraudit (16 oktober 2026)

**Scope:** uitsluitend de in de chat gewijzigde Leadscanner-route, documentatie, live private Leads-bronnen, bestaande 450-review en toegangsgrenzen. **Geen klanten, e-mailadressen, onderwerpregels of mailinhoud** worden in dit openbare rapport opgeslagen.

## Auditstrategie en opdrachtprompt

> Bevries de actuele baseline en vergelijk de repo, geinstalleerde Leads-Skill, actieve Project Leads-bron, privé-Sheets en werkelijk uitgevoerde CI-/runtimejobs. Gebruik context-engineering en retrieval-grounding voor bronselectie; gap-only-optimization als default NO_CHANGE; independent-verifier met echte bron-/runreadback; adversarial, property-based en failure-injection voor vertrouwen, herstel, duplicaten en sheetschema; end-to-end-verification voor bron → Verified → Approved/History → WebsiteEvidence → AutoDraftState/DraftQueue → IMAP Drafts. Classificeer elke claim PASS, FAIL, BLOCKED of NOT_TESTED. Geen verzendactie of live klantdummy; herstel alleen bewezen harde failures met kleine patches en regressies. Eerder groene onderdelen blijven ongewijzigd.

De gebruikte zeven bronstappen: (1) live projectdocument en beide privé-Sheets gecontroleerd; (2) geinstalleerde `leads`- en `webactueel-workflow`-Skill gecontroleerd; (3) GitHub `main`, scripts, workflows en PR/CI bekeken; (4) Library voor eerdere audits gecontroleerd; (5) YouTube-kennisindex gezocht, geen voor deze Python/Sheets-API-fout relevanter primair bewijs geselecteerd; (6) Python, Google Sheets, GitHub Actions en Nederlandse emailregels tegen officiele bronnen gehouden; (7) regressie/CI/runtime/live readback en privacygrenzen gecontroleerd.

## Bewijs en gecontroleerde invarianten

| Controle | Uitkomst | Bewijs |
|---|---|---|
| Bestaande reviewset en unieke concept-ID's | PASS, 450/450 | privé `Review450`; ID-only read |
| Actuele QA-scoregrenzen | PASS, hoogste 9,5/10, 0 boven 10 | privé `QA450Actueel` |
| Niet-verzendklaar | 37 expliciete bron-/niet-versturenstatussen, geen automatische vrijgave | privé `QA450Openstaand` en `QA450Actueel` |
| Actieve Approved/History/Evidence-koppeling | PASS, 57 Approved, 57 Evidence; 0 ontbrekende identiteit-koppelingen; 526 bewaarde LeadHistory | privé Sheet, geaggregeerde check |
| Privé-opslag | PASS, beide Sheets niet publiek; bestaand serviceaccount `writer` | Google Drive live permissions readback |
| Nieuwe automatische conceptregistratie | Nog 0 productie-items in `AutoDraftState`; 50 bestaande DraftQueue-records behouden | privé Draft Queue readback |
| Live websiteverificatie | PASS 57 websites, 32,14 s geforceerd | [run 38813849977](https://github.com/Yolol100/Leadscanner/actions/runs/38813849977) |
| Cachehergebruik | PASS 46 van 57 hergebruikt, 11 opnieuw bezocht, 16,35 s | [run 38814017280](https://github.com/Yolol100/Leadscanner/actions/runs/38814017280) |
| Live IMAP-auth + Drafts read-only | PASS, status `imap_drafts_examined_readonly`, 0 writes/sends | [run 38814887783](https://github.com/Yolol100/Leadscanner/actions/runs/38814887783) |
| Laatste code-regressies | PASS 313/313; bewijs van falende defectfixture op oude versie en geslaagde suite na patch | [PR #1699](https://github.com/Yolol100/Leadscanner/pull/1699), [test-failure run 38817386437](https://github.com/Yolol100/Leadscanner/actions/runs/38817386437), [test-pass run 38817565040](https://github.com/Yolol100/Leadscanner/actions/runs/38817565040) |

## Gerepareerde harde fout

**F1 — lege Google Sheets evidence-cache.** Wanneer een eerder aangemaakt, nog leeg `WebsiteEvidence`-tabblad een geldige HTTP-200 `values.get` zonder `values` gaf, faalde `fast_website_evidence._read` voordat `_cache` herstel kon uitvoeren. Een nieuwe reproductietest faalde op de oude code in run 38817386437 (`private_evidence_sheet_shape_invalid`). De kleinste patch accepteert uitsluitend een verder geldig leeg range-antwoord als `[]`, terwijl verplicht bronheaderbewijs onverminderd fail-closed blijft. PR #1699 is gemerged; 313 volledige en 28 gerichte evidentietests slaagden op de gefixte versie. Geen klant- of mailboxwrites.

## Nog openstaande bewijs-/architectuurpunten (niet als PASS tellen)

**P1 — Skill/uitvoering-drift (bewezen).** De geinstalleerde `skills://leads` schrijft nog een handmatige `#1659`-trigger en *exact zes vaste* `first-touch`-templates voor. Het geautoriseerde projectdocument en `fresh-leads.yml` bevatten daarnaast een geplande `auto_first_drafts`-job die nieuwe factspecifieke conceptteksten maakt. De vier stappen en handmatige send-grens blijven gelijk, maar de instructiearchitectuur is nog niet synchroon. Herstel vereist een uitdrukkelijk afgebakende optionele automatische variant in de **bestaande** Skill en de bijbehorende zes templates; voeg geen CRM of extra masterrouter toe.

**P1 — niet-atomische overgang tussen geverifieerde lead en bronbewijs (statisch bevestigd risico; geen bewezen live dataverlies).** `verified_fill.main` roept eerst `store_approved` aan (schrijft `Approved` + `LeadHistory` atomair), en pas daarna `store_preverified_approved` (aparte `WebsiteEvidence`-write). Bij falen in stap twee zijn bedrijf en permanente historie al vastgelegd maar bewijs ontbreekt; de scheduled auto-conceptjob kan dat record niet doorlaten. Latere zoekruns onderdrukken dat bedrijf juist dankzij historie; automatische catch-up voor de originele run is niet bewezen. Ontwerp eerst een idempotent recoveryscenario met een defectfixture voordat code wordt aangepast.

**P2 — volwaardige productie-run nog `NOT_TESTED`.** De echte geplande keten die nieuwe leads als eerste concept in Mijn.Host Drafts opslaat, inclusief per-ID exacte readback bij partial failure, is nog niet aangetoond. De huidige groene tests betreffen synthetische cases en read-only IMAP; ze geven geen garantie voor de eerste autonome batch. Do not claim end-to-end Go voordat die batch en rollback/hertest bewezen zijn.

**P2 — GitHub cron is best-effort.** GitHub kan scheduled jobs vertragen of in uitzonderingen droppen en kan public-repo schedules na 60 dagen inactiviteit uitschakelen. Een watchdog of gerichte alert ontbreekt in deze gecontroleerde scope; maak hier geen minuut-/100%-beschikbaarheidsgarantie van.

**Rechtmatigheid:** gepubliceerd bedrijfse-mailadres is niet automatisch toestemming voor ongevraagde commerciële mail. Blijf alle concepten uitsluitend Drafts; mens beoordeelt wettelijke basis, identiteit, relevantie en afmelding vóór handmatig versturen. Zie artikel 11.7 Telecommunicatiewet en ACM.

## Eindoordeel

**GO** voor geverifieerd websiteonderzoek, privé-broncache, bestaande dedupe/historie en read-only Mijn.Host-toegang. **NO-GO voor de claim "volledig autonome nieuwe-conceptketen aantoonbaar end-to-end gevalideerd"** totdat beide P1's en de eerste werkelijk gemeten batch zijn afgehandeld. Geen automatische verzending, geen manipulatie van oude 450, geen nieuwe scoreclaims of conversievoorspellingen.
## Herstelstatus 16 oktober 2026 — P1/P2 daadwerkelijk opgepakt

- **P1 atomair:** `verified_fill.main` leidt de website-feiten uit de oorspronkelijke geverifieerde pagina's af **vóór** opslag. `approved_handoff.store_approved(..., evidence_rows=...)` voegt nu `Approved`, permanente `LeadHistory` en `WebsiteEvidence` samen in één geautoriseerde Google Sheets `batchUpdate`. Een eventueel ontbrekend leeg evidence-tabblad wordt eerst aangemaakt, zonder bedrijf of historie vast te leggen. Een HTTP-fout laat volgens de Sheets-atomiciteitsgarantie geen gedeeltelijk bijgewerkte records achter. Synthetische tests dekken mislukte commit, retry, onjuiste readback en ontbrekende pagina-inhoud. Echte klantdata/450 blijven onaangeroerd.
- **P1 Skill-drift:** de geïnstalleerde `skills://leads` was manual-only. Er is een complete, gevalideerde update-**ZIP** gemaakt op basis van de oorspronkelijke Skill (inclusief alle historische referenties). De vier stappen en handmatige `#1659`-route blijven intact; een aparte optionele `references/automated-first-draft.md` legt de eerder expliciet gevraagde geplande route vast. **Let op: het ZIP-pakket moet nog in ChatGPT worden geïnstalleerd.** Alleen het genereren van het pakket verandert de actieve Skill niet.
- **P2 integratie:** de nieuwe `tests/test_auto_first_draft_e2e.py` gebruikt de echte code voor private Sheets-parsing, queue-integriteit, MIME en IMAP `\\Draft` APPEND plus exacte readback, met uitsluitend offline in-memory transportfakes. De negatieve case onderbreekt de mailbox ná een gecommitte privé queue en bewijst veilig hervatten zonder dubbel concept. De laatste volledige CI moet voorafgaand aan merge groen zijn; deze test is géén bewijs dat de eerste daadwerkelijke productiebatch al is uitgevoerd.
- **P2 planning:** `scripts/schedule_health.py` en `.github/workflows/lead-schedule-health.yml` controleren op werkdagen of de echte geplande `schedule`-runs na vijf uur speling bestaan en of zowel `discover` plus `auto_first_drafts` als `research` slagen. Alle API-calls zijn read-only; geen credentials, persoonsdata of e-mails in logs. Daarnaast kan een onafhankelijke externe conditiebewaking gemiste GitHub-runs melden. GitHub-cron blijft best-effort, geen realtimegarantie.

De bestaande historische uitsluitingen, 50 bestaande Draft Queue-rijen, 450 reviewrecords, afmeldingen, privacyrechten, vier user-facing stappen en het verbod op SMTP/senden zijn onveranderd.

### Restacceptatie
**Proven in code/offline:** één gezamenlijke Sheets-opslag, hersteltoets, geen-send eerste concept + IMAP readback, monitoring-oracles. **Pas na de eerste toekomstige geplande productie-run bewezen:** echte nieuwe geverifieerde bedrijfskandidaten tot volledige Mijn.Host-conceptreadback, met correcte opt-out en menselijke vrijgave. Geen kunstmatige 10/10 of verzendclaim.
