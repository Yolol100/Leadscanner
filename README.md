# Leadscanner

Optionele Webactueel browser-auditharness voor read-only controle van publieke bedrijfswebsites. De normale Starteractie-leadworkflow gebruikt deze repository niet.

## Gebruik

Alleen bij een expliciete website-audit, technische scan of rescan. De harness kan begrensde Crawlee + Playwright-inspectie uitvoeren op desktop en mobiel en technische/browserbevindingen als bewijs teruggeven.

Niet gebruiken voor leadselectie, e-mailonderzoek, verzendgrond, leadlijsten, mailcopy, conceptmails, scoring, prioritering of follow-ups.

## Veiligheid

- maximaal vier kernpagina's per target;
- GET/HEAD-only; geen formulieren, bestellingen, betalingen of boekingen;
- publieke officiële website vereist;
- TLS/robots/sitemap- en netwerkgrenzen blijven actief;
- Axe, Lighthouse, LanguageTool, Linkinator en tech-detect zijn alleen aanvullende auditcontext;
- scannerbevindingen veranderen nooit automatisch outreachstatus of geschiktheid.

## Repository hygiene

`main` bevat alleen de generieke harness. Klant-, site-, request- en run-specifieke input/evidence blijft tijdelijk of run-scoped.

- `sites.txt` is lokale tijdelijke input en staat in `.gitignore`;
- `requests/scan.json` hoort alleen op een tijdelijke runtimebranch;
- Actions-resultaten blijven artifacts en worden niet naar `main` gecommit.

## Starten

GitHub Actions: gebruik **Actions -> Website Scan -> Run workflow** met één publieke officiële bedrijfs-URL, of de gecontroleerde tijdelijke request-file route.

Lokaal:

```bash
cp sites.example.txt sites.txt
npm ci
npm run scan
```

Commit `sites.txt` nooit.

## Bewijsgrens

De scanner levert technische/browserobservaties. Hij bepaalt geen leadgeschiktheid, Leadscore, prioriteit, verzendgrond, conversiewinst, WCAG-conformiteit of productiegeschiktheid.
