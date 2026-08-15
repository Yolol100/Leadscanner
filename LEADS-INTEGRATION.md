# Leads integration contract

Deze repository is een uitvoeringscapability voor de Webactueel Leads Skill. De repository is nooit eigenaar van de Leadscore.

## Wanneer gebruiken

Gebruik de Leadscanner wanneer de Leads-workflow echte websitekwalificatie nodig heeft:

- nieuwe kandidaat na Registry-voorcheck en officiële websitebevestiging;
- kwalificatie van een opgegeven bedrijfswebsite;
- expliciete rescan/reactivate van een bestaande lead;
- hercontrole wanneer geldig desktop+mobiel browserbewijs ontbreekt of verouderd is;
- dezelfde-dag hercontrole voordat een Gmail-write wordt voorbereid wanneer de Leads-regels dit eisen.

Gebruik de Leadscanner niet voor:

- alleen zoekwoord- of sectoronderzoek;
- alleen Registry-deduplicatie;
- alleen officiële bedrijfsbevestiging;
- alleen contact/e-mailadres zoeken;
- mailcopy, Gmail-history, drafts of follow-ups.

## Waarom gebruiken

De Leads Skill vereist voor echte kwalificatie gecontroleerd desktop- én mobiel browserbewijs van de minimumroute. Deze repository levert die browserlaag en aanvullende technische signalen.

## Uitvoering

1. Geef één officiële website via `target_url`, of gebruik een vooraf gecontroleerde lijst in `sites.txt`.
2. Draai `.github/workflows/scan.yml`.
3. Crawlee + Playwright voeren de read-only GET/HEAD browserroute uit op desktop en mobiel.
4. Sitemap/robots, Linkinator en tech-detect draaien als supplementaire checks; LanguageTool en Lighthouse zijn optioneel.
5. Draai `npm run handoff:leads` na `npm run enrich`.
6. Gebruik `scan-results/leads-handoff.json` als overdracht naar Leads.

## Handoffregels

`leads-handoff.json` levert browserbewijs als `runtime_surface=controlled-browser` en bewaart `runtime_detail=github_actions_crawlee_playwright` voor provenance.

De adapter maakt één `full_route` bewijsrecord per device. Pagina-evidence blijft apart aanwezig. Scannerbevindingen worden alleen als `finding_candidates` doorgegeven en hebben altijd `requires_leads_validation=true` en `automatic_score_effect=false`.

De Leads Skill moet daarna zelf:

- `lead_id`, bedrijf, regio en officiële bedrijfsbevestiging binden;
- maximaal drie observaties valideren;
- `webactueel_fit`, `fit_reason` en passend bewijs bepalen;
- de formele Leads-validator/scoring uitvoeren;
- Registrystatus terugschrijven.

## Stop- en fallbackregels

- Geen complete desktop+mobiel route: niet kwalificeren; markeer als browser/handoff-blocked.
- Geen mogelijkheid om de GitHub workflow op de actuele surface te starten: `handoff_required`; simuleer geen scan.
- Een Linkinator-, Lighthouse-, LanguageTool-, Axe- of tech-detect-signaal verhoogt nooit zelfstandig de Leadscore.
- Formulieren, bestellingen, betalingen en boekingsbevestigingen worden nooit verzonden of afgerond.

## Eigenaarschap

- Leads Skill: probleemvalidatie, Webactueel-fit, prioriteit 1-5, contact/outreach.
- Leadscanner: gecontroleerde browseruitvoering en technische kandidaat-signalen.
- Lead Registry: persistente operationele leadstatus.
