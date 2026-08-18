# Leadscanner

Generieke Webactueel leadscan- en browser-evidenceharness voor read-only controle van publieke bedrijfswebsites. De `leads` Skill blijft eigenaar van kwalificatie en score; deze repository levert alleen reproduceerbaar bewijs.

## Wat de harness doet

- begrensde Crawlee + Playwright-inspectie op desktop en mobiel;
- maximaal vier kernpagina's per target;
- GET/HEAD-only browsergrens: geen formulieren, bestellingen, betalingen of boekingen;
- signalen voor HTTP/JavaScript-fouten, afbeeldingen, overflow, placeholders, CTA's en axe-risico's;
- optionele Lighthouse- en lokale LanguageTool-controles;
- sitemap/robots-discovery, Linkinator en tech-detect als aanvullende signalen;
- run-scoped screenshots, JSON-evidence, `summary.md` en Leads-handoff in een GitHub Actions-artifact.

## Repository hygiene

`main` bevat uitsluitend de generieke harness. Klant-, site-, scan- en run-specifieke input of evidence wordt niet permanent opgeslagen.

- `sites.txt` is lokale tijdelijke invoer en staat in `.gitignore`.
- `requests/scan.json` is tijdelijke requeststate en staat in `.gitignore`.
- Een connectorgestuurde request mag alleen op een tijdelijke `runtime/**`-branch bestaan.
- GitHub Actions-resultaten blijven run-scoped artifacts en worden niet terug naar `main` gecommit.
- Gebruik `sites.example.txt` alleen als leeg generiek voorbeeld; voeg daar geen targets aan toe.

## Scan starten

### GitHub Actions

Gebruik **Actions -> Website Scan -> Run workflow** en vul één publieke officiële bedrijfs-URL in. Wanneer een file-write route nodig is, maak een tijdelijke `runtime/**`-branch vanaf de actuele `main`, plaats daar precies de tijdelijke `requests/scan.json`, lees het Actions-resultaat terug en verwijder de tijdelijke branch na closure.

### Lokale batch

```bash
cp sites.example.txt sites.txt
# vul sites.txt lokaal met één URL per regel
npm ci
npm run scan
```

Commit `sites.txt` nooit.

## Reproduceerbare runtime

- Node `22.23.2` en npm `10.9.8` in GitHub Actions;
- exacte npm-versies en lockfile-installatie met `npm ci`;
- externe Actions op vaste commit-SHA's;
- productie-dependencyaudit en smoke/contractchecks blijven actief.

## Bewijsgrenzen

De scanner levert technische/browserobservaties, geen automatische leadkwalificatie. Toolboxsignalen mogen zelfstandig geen Leadscore bepalen. Volledige WCAG-conformiteit, conversiewinst of productiegeschiktheid worden niet door deze harness bewezen.
