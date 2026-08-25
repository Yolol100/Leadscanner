# Leads integration contract

Leadscanner is een optionele, read-only website-auditcapability. De normale Webactueel Starteractie-workflow gebruikt deze repository niet.

## Alleen gebruiken wanneer

De gebruiker expliciet vraagt om een website-audit, technische scan of rescan van een bevestigde officiële bedrijfswebsite.

Niet gebruiken voor:

- bedrijven/websites vinden;
- Registry-deduplicatie;
- e-mailadressen zoeken;
- verzendgrond controleren;
- leadlijsten maken;
- mailcopy of Gmail/Outlook-concepten;
- Leadscore, prioriteit of follow-ups.

## Input

Gebruik per run één bevestigde publieke `http`/`https`-URL via `requests/scan.json` of expliciete `workflow_dispatch`. `sites.txt` is alleen handmatige lokale batchinput en nooit een verborgen fallback.

## Veiligheidsgrens

- read-only `GET`/`HEAD`;
- blokkeer localhost, private/link-local/metadata-ranges en riskante actie-URL's;
- respecteer robots/sitemaproute;
- geen formulieren, login, bestelling, betaling, boeking of andere state-changing actie;
- TLS blijft streng;
- `401`, `403` en `429` zijn toegangsblokkades, geen salesbevindingen.

## Uitvoer

Crawlee + Playwright mogen desktop/mobiel browserbewijs en technische kandidaatbevindingen opleveren in `scan-results/leads-handoff.json`. Supplementaire signalen van Axe, Lighthouse, LanguageTool, Linkinator of tech-detect zijn alleen auditcontext.

De scanner bepaalt nooit geschiktheid, prioriteit, Leadscore, verzendgrond of outreachstatus. De Leads Skill gebruikt de scan alleen als aparte audituitkomst wanneer de gebruiker daarom vroeg.

## Runtime

1. GitHub request-file of `workflow_dispatch` wanneer run/artifact-readback beschikbaar is.
2. Anders lokale Codex/CLI-runtime met `npm ci` en de bestaande scancommando's.
3. Zonder bewezen uitvoerroute: `handoff_required`; simuleer geen browserbewijs.

## Hygiene

Houd klant-, site- en run-specifieke input/evidence buiten `main`. GitHub Actions-resultaten blijven run-scoped artifacts. Bestaande CI-, dependency-, TLS- en supply-chainchecks blijven gelden.
