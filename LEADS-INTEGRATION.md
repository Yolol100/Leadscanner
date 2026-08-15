# Leads integration contract

Deze repository is een uitvoeringscapability voor de Webactueel Leads Skill. De repository is nooit eigenaar van de Leadscore.

## Wanneer gebruiken

Gebruik de Leadscanner wanneer de Leads-workflow echte websitekwalificatie nodig heeft:

- nieuwe kandidaat na Registry-voorcheck en officiële websitebevestiging;
- kwalificatie van een opgegeven bedrijfswebsite;
- expliciete rescan/reactivate van een bestaande lead;
- hercontrole wanneer geldig desktop+mobiel browserbewijs ontbreekt of volgens Leads niet meer vers genoeg is;
- dezelfde-dag hercontrole voordat een Gmail-write wordt voorbereid wanneer de Leads-regels dit eisen.

Gebruik de Leadscanner niet voor:

- alleen zoekwoord- of sectoronderzoek;
- alleen Registry-deduplicatie;
- alleen officiële bedrijfsbevestiging;
- een reeds geldige voldoende verse websitecontrole;
- alleen contact/e-mailadres zoeken;
- mailcopy, Gmail-history, bestaande drafts of follow-ups.

## Waarom gebruiken

De Leads Skill vereist voor echte kwalificatie gecontroleerd desktop- én mobiel browserbewijs van de minimumroute. Deze repository levert precies die browserlaag en aanvullende technische signalen. Crawlee/Playwright leveren primair bewijs; sitemap/robots, Linkinator, LanguageTool, Lighthouse en tech-detect blijven ondersteuning en mogen nooit zelfstandig een Leadscore verhogen.

## Runtimekeuze

Kies eerst de echte uitvoerroute; simuleer geen browserrun.

1. **GitHub Actions** — gebruik `.github/workflows/scan.yml` wanneer de actuele GitHub-capability `workflow_dispatch` werkelijk kan starten én de run/artifact kan teruglezen.
2. **Codex/CLI lokale repo-runtime** — gebruik de uitgecheckte repository wanneer Node/npm/Chromium aantoonbaar beschikbaar zijn. Voer dan `npm ci`, Chromium-installatie, `npm run scan`, `npm run enrich` en `npm run handoff:leads` uit.
3. **Geen uitvoerroute** — geef `handoff_required`. Een zichtbare GitHub-connector zonder workflow-dispatch is geen bewijs dat de scan kan worden gestart.

## Uitvoering

1. Doe eerst de Leads Registry-voorcheck, behalve bij expliciete rescan/reactivate.
2. Bevestig de officiële bedrijfswebsite vóór formele kwalificatie.
3. Geef één officiële website via `target_url`, of gebruik een vooraf gecontroleerde lijst in `sites.txt`.
4. Laat de scanner het sitetype en de kernroute bepalen. Als Leads het sitetype al heeft vastgesteld, vergelijk dat na de scan met `site_type_detected`; los een materieel verschil op vóór scoring.
5. Crawlee + Playwright voeren de read-only GET/HEAD browserroute uit op desktop en mobiel.
6. Sitemap/robots, Linkinator en tech-detect draaien als supplementaire checks; LanguageTool en Lighthouse zijn optioneel.
7. Draai `npm run handoff:leads` na `npm run enrich`.
8. Gebruik `scan-results/leads-handoff.json` als overdracht naar Leads.

## Handoffregels

`leads-handoff.json` gebruikt formaat `webactueel-leadscanner-handoff/1.1` en levert:

- een deterministische `lead_id` op basis van het genormaliseerde domein;
- `runtime_surface=controlled-browser` met `runtime_detail=github_actions_crawlee_playwright` voor provenance;
- één echt `full_route` bewijsrecord per device;
- aparte pagina-evidence waarbij `route_complete=false`, zodat een losse screenshot nooit een complete route claimt;
- Leads-genormaliseerde routecategorieën zoals `presentatie`, `navigatie`, `contact`, `product`, `bestellen` en `betalen`;
- alleen `finding_candidates`, altijd met `requires_leads_validation=true` en `automatic_score_effect=false`;
- expliciet welke context nog uit Leads moet komen voordat scoring mag plaatsvinden.

De Leads Skill moet daarna zelf:

- `TARGET_SPEC`, bedrijf, regio en officiële bedrijfsbevestiging binden;
- `site_type_detected` vergelijken met de reeds bevestigde kandidaatcontext;
- maximaal drie observaties kiezen en aan passende evidence-ID's binden;
- `webactueel_fit`, `fit_reason` en passend bewijs bepalen;
- de formele Leads-validator/scoring uitvoeren;
- Registrystatus terugschrijven.

## Toolselectie binnen de repo

- **Crawlee:** altijd voor crawlregie van een echte websitecontrole.
- **Playwright:** altijd voor formele desktop+mobiel kwalificatie.
- **Sitemap/robots:** standaard als route-discovery-support.
- **Linkinator:** standaard aanvullend op kernroutes; nooit zelfstandig scorebewijs.
- **Tech-detect:** standaard fit-support; nooit zelfstandig probleemernst.
- **LanguageTool:** alleen wanneer Nederlandse copycontrole relevant of expliciet gevraagd is.
- **Lighthouse:** alleen als aanvullende performancecontext bij een reeds interessante kandidaat of expliciete performancevraag.

## Stop- en fallbackregels

- Geen complete desktop+mobiel route: niet kwalificeren; markeer browser/handoff-blocked.
- Geen uitvoerroute op de actuele surface: `handoff_required`; simuleer geen scan.
- Sitetype of kernroute materieel in conflict met de bevestigde kandidaatcontext: review/rescan vóór scoring.
- Een finding zonder bruikbaar browserbewijs mag niet als formele observatie worden gebruikt.
- Een Linkinator-, Lighthouse-, LanguageTool-, Axe- of tech-detect-signaal verhoogt nooit zelfstandig de Leadscore.
- Formulieren, bestellingen, betalingen en boekingsbevestigingen worden nooit verzonden of afgerond.

## Eigenaarschap

- Leads Skill: probleemvalidatie, Webactueel-fit, prioriteit 1-5, contact/outreach.
- Leadscanner: gecontroleerde browseruitvoering en technische kandidaat-signalen.
- Lead Registry: persistente operationele leadstatus.
