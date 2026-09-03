# Leads integration contract

Leadscanner is een optionele, read-only website-auditcapability. De normale Instantly/Leads-flow gebruikt deze repository niet standaard.

## Gebruik wanneer

Gebruik de scanner wanneer één van deze twee routes geldt:

1. de gebruiker vraagt expliciet om een website-audit, technische scan of rescan van een bevestigde officiële bedrijfswebsite; of
2. Leads heeft na de lichte officiële-sitecheck een **technisch bewijs-gat** voor de gekozen outreach-invalshoek en geen even sterke, eenvoudiger bewezen niet-technische invalshoek is beschikbaar.

Typische bewijs-gaten: performance/Core Web Vitals, mobiel rendergedrag, kapotte route/link, technische accessibility-kandidaat of relevante tech-detectie.

Niet gebruiken voor:

- bedrijven/websites vinden;
- Registry-deduplicatie;
- e-mailadressen zoeken of verifiëren;
- verzendgrond/compliance controleren;
- leadlijsten maken;
- mailcopy of Outlook-/Instantly-payloads maken;
- Leadscore of `Opportunity Priority`;
- intent-/triggerweging of bronverzadigingsscore;
- sender-preflight, SPF/DKIM/DMARC-besluiten of sender-health;
- unsubscribe/opt-out-keuze;
- domein-/mailboxrotatie, volume- of schaalbeslissingen;
- campaign follow-ups, replyhandling of CRM/deal learning;
- batchbreed scannen van alle Instantly-leads.

## Input

Gebruik per run één bevestigde publieke `http`/`https`-URL via `requests/scan.json` of expliciete `workflow_dispatch`. `sites.txt` is alleen handmatige lokale batchinput en nooit een verborgen fallback.

Leads geeft naast de target-URL alleen de technische bewijsbehoefte door. Instantly-data, campaigndata, Opportunity Priority en sender-health zijn geen scannerinput en worden niet in de repository opgeslagen.

## Veiligheidsgrens

- read-only `GET`/`HEAD`;
- blokkeer localhost, private/link-local/metadata-ranges en riskante actie-URL's;
- respecteer robots/sitemaproute;
- geen formulieren, login, bestelling, betaling, boeking of andere state-changing actie;
- TLS blijft streng;
- `401`, `403` en `429` zijn toegangsblokkades, geen salesbevindingen.

## Uitvoer

Crawlee + Playwright mogen desktop/mobiel browserbewijs en technische kandidaatbevindingen opleveren in `scan-results/leads-handoff.json`. Supplementaire signalen van Axe, Lighthouse, LanguageTool, Linkinator of tech-detect zijn alleen auditcontext.

De scanner bepaalt nooit geschiktheid, prioriteit, Leadscore/Opportunity Priority, intent, verzendgrond, compliance, sender-health, volume, unsubscribe/opt-out of outreachstatus. Leads gebruikt alleen de relevante evidence om de technische claim te bevestigen of te verwerpen. Bij onvoldoende bewijs wordt de claim niet gebruikt.

Een scannerresultaat mag daarom nooit punten toevoegen aan Opportunity Priority en mag nooit een `throttle`, `pause` of `blocked` sender-/compliancestatus opheffen.

## Runtime

1. GitHub request-file of `workflow_dispatch` wanneer run/artifact-readback beschikbaar is.
2. Anders lokale Codex/CLI-runtime met `npm ci` en de bestaande scancommando's.
3. Zonder bewezen uitvoerroute: `handoff_required`; simuleer geen browserbewijs. Leads kiest dan een andere bewezen invalshoek of blokkeert de technische claim.

## Hygiene

Houd klant-, site-, Instantly-, campaign- en run-specifieke input/evidence buiten `main`. GitHub Actions-resultaten blijven run-scoped artifacts. Bestaande CI-, dependency-, TLS- en supply-chainchecks blijven gelden.
