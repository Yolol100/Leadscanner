# Leads integration contract

Deze repository is een uitvoeringscapability voor de Webactueel Leads Skill. De repository is nooit eigenaar van de Leadscore.

## Wanneer gebruiken

Gebruik de Leadscanner voor nieuwe kwalificatie, expliciete rescan/reactivate of wanneer geldig desktop+mobiel browserbewijs ontbreekt of volgens Leads te oud is. Gebruik hem niet voor alleen keywordonderzoek, Registry-deduplicatie, officiële bedrijfsbevestiging, contactonderzoek, mailcopy, Gmail-history of follow-ups.

## Verplichte precondities

1. Doe de Leads Registry-voorcheck waar die volgens Leads vereist is.
2. Bevestig de officiële bedrijfswebsite.
3. Op Chat: schrijf precies één source-bound request naar `requests/scan.json` en gebruik alleen die route wanneer GitHub file-write plus Actions run/artifact-readback beschikbaar zijn.
4. Via GitHub UI/CLI/API mag `workflow_dispatch` worden gebruikt wanneer die capability werkelijk beschikbaar is; geef dan altijd precies één `target_url`.
5. Gebruik `sites.txt` alleen voor een expliciet gevraagde batchscan. Een lege URL of ontbrekende dispatch-capability mag nooit stil terugvallen op `sites.txt`.
6. Geef het door Leads bevestigde `site_type` als `site_type_hint=service|shop|booking` wanneer dat bekend is. De scanner rapporteert daarnaast `site_type_detected`; een materieel verschil blijft een Leads-reviewpunt vóór scoring.

## Request-file contract

Een ingeschakeld `requests/scan.json` bevat minimaal:

- `enabled=true` en een unieke veilige `request_id`;
- `requested_by`, `owner=leads` en `project_id=project-leads`;
- `for`: voor wie/waarvoor het bewijs wordt verkregen;
- `task`: wat de repo moet doen;
- `why`: waarom nieuw browserbewijs nodig is;
- `trigger_when`: wanneer deze capability mag starten;
- `do_not_trigger_when`: wanneer de repo juist niet mag starten;
- exact één `target_url` plus optioneel bevestigd `site_type_hint`;
- begrensde scaninstellingen;
- `source_context.project_id=project-leads` en de actuele `source_set_version`.

De workflow valideert dit contract vóór npm, browser- of netwerkruntime wordt gestart. `enabled=false` is een geldige idle/self-test state en start geen scan.

## Veiligheidsgrens

De scanner werkt fail-closed waar een automatische browseractie risico kan opleveren:

- alleen publieke `http`/`https` targets; localhost, private, link-local, gereserveerde en metadata-IP-ranges worden geblokkeerd;
- DNS wordt gecontroleerd vóór server-side fetches en browserverzoeken;
- documentnavigatie blijft op de officiële site; cross-site documentredirects worden geblokkeerd;
- alleen `GET`/`HEAD`; niet-leesmethoden worden geblokkeerd;
- bekende actie-URLs zoals logout, unsubscribe, account-delete, add-to-cart en confirm-routes worden niet automatisch bezocht;
- TLS-validatie blijft streng; certificaatfouten worden niet genegeerd;
- third-party HTTP-fouten zijn geen Leadscanner-probleemfinding;
- `401`, `403` en `429` zijn scan-/toegangsblokkades, geen salesprobleem;
- `safe_boundary_respected` wordt afgeleid uit gemeten boundary-events en is geen hardcoded claim.

## Routekeuze

1. Voer vóór Playwright een publieke target-preflight uit.
2. Lees `robots.txt`; pas de relevante `User-agent`, `Allow` en `Disallow` regels toe. Een tijdelijke robots-fout (`429`/`5xx`) blokkeert de scan conservatief.
3. Lees toegestane sitemaps en bouw routekandidaten.
4. Combineer homepage-links en sitemapkandidaten met het optionele `site_type_hint`.
5. Bezoek maximaal de afgesproken kernroute op desktop en mobiel.

Sitemap/robots is daarmee route-input, niet alleen post-scan enrichment.

## Browser- en evidencecontract

Crawlee + Playwright leveren het primaire browserbewijs. Iedere paginacapture bevat:

- `planned_url` en de feitelijke `runtime_url`;
- device, viewport en routecategorie;
- hashgebonden screenshotbewijs;
- `route_complete=false` op losse paginacaptures.

Volledige routedekking wordt exact bepaald: iedere geplande URL + rol moet per device een passende capture hebben. Alleen daarna wordt een apart `full_route` bewijsrecord `route_complete=true`. Aantallen screenshots alleen zijn nooit voldoende.

`scan-results/leads-handoff.json` blijft formaat `webactueel-leadscanner-handoff/1.1` voor compatibiliteit met de Leads Skill. Het bevat daarnaast de gemeten `safety`-status, `site_type_hint`, `site_type_detected` en `site_type_used`.

## Supplementaire tools

- Sitemap/robots: route-discovery en toegangsbeleid.
- Linkinator: alleen same-site, lage concurrency, riskante actie-URLs overslaan.
- Tech-detect: fit-support, geen probleemernst.
- LanguageTool: optioneel; lokale distributie is vastgepind en SHA-256-gecontroleerd.
- Lighthouse: optioneel; strict TLS en alleen aanvullende context.
- Axe: accessibility-signaal; nooit zelfstandig kwalificatiegrond.

Geen supplementair signaal mag zelfstandig `priority`, `qualified` of Leadscore bepalen.

## Runtimekeuze

1. **GitHub request-file** — voorkeursroute op Chat wanneer `requests/scan.json` geschreven kan worden en Actions run/artifact-readback beschikbaar is.
2. **GitHub `workflow_dispatch`** — voor UI/CLI/API-surfaces die dispatch én readback werkelijk aanbieden.
3. **Codex/CLI repo-runtime** — alleen bij aantoonbare repo/Node/npm/Chromium-runtime: `npm ci`, Chromium installeren, `npm run scan`, `npm run enrich`, `npm run handoff:leads`.
4. **Geen uitvoerroute** — `handoff_required`; simuleer geen browserrun en gebruik `sites.txt` niet als verborgen fallback.

## Handoff naar Leads

De Leads Skill blijft eigenaar van:

- officiële bedrijfscontext en sitetypebevestiging;
- validatie van maximaal drie bewezen observaties;
- `problem_severity` versus `webactueel_fit`;
- prioriteit 1–5 en `qualified`;
- contact-, juridische, privacy- en outreachpoorten;
- Registry- en Gmailstatus.

De Leadscanner levert alleen browserbewijs en `finding_candidates` met `requires_leads_validation=true` en `automatic_score_effect=false`. De Leads Skill bindt het teruggelezen artifact vóór gebruik aan `webactueel-leadscanner-ingest/1.0` met repository, workflow, volledige commit-SHA, ref, run-ID, artifactnaam, artifact-SHA-256 en `artifact_readback_verified=true`.

## CI en supply chain

- npm-dependencies zijn lockfile-gebonden en worden met `npm ci` geïnstalleerd.
- productie-dependencies krijgen in CI `npm audit --omit=dev --audit-level=high`.
- gebruikte GitHub Actions zijn aan volledige commit-SHA's gepind.
- Dependabot controleert wekelijks npm- en GitHub Actions-dependencies; updates moeten dezelfde smoke- en integratietests doorlopen.
- `main` hoort met vereiste statuschecks beschermd te zijn. Als repositoryrechten dit niet via de automation-capability toestaan, is dat een expliciete repository-adminactie en geen codeclaim.
