# Leadscanner

> **Portfoliostatus:** Actief ondersteunend · private Webactueel browser-auditharness

**Rol in het platform:** Leadscanner levert uitsluitend ontbrekend technisch browserbewijs aan de Webactueel Leads-flow. Hij vindt geen leads, verstuurt geen outreach en beslist niet over leadfit, compliance of prioriteit. De normale flow gebruikt deze private capability alleen bij een aantoonbaar technisch bewijsgat.

Optionele Webactueel browser-auditharness voor read-only controle van publieke bedrijfswebsites. De normale Instantly/Leads-flow gebruikt deze repository niet standaard.

## Gebruik

Gebruik de harness alleen wanneer:

1. Leads na de lichte officiële-sitecheck een **technisch bewijs-gat** heeft voor de gekozen outreach-invalshoek; of
2. de gebruiker expliciet een website-audit, technische scan of rescan vraagt.

Typische bewijs-gaten zijn performance/Core Web Vitals, mobiel rendergedrag, een kapotte route/link of een technische accessibility-kandidaat. Als een even sterke, al bewezen niet-technische invalshoek beschikbaar is, gebruik die en sla de scanner over.

De harness kan begrensde Crawlee + Playwright-inspectie uitvoeren op desktop en mobiel en technische/browserbevindingen als bewijs teruggeven.

Niet gebruiken voor leadfinding, e-mailonderzoek, verzendgrond, leadlijsten, mailcopy, Instantly-campaignbeheer, scoring, prioritering of follow-ups. Scan nooit standaard een volledige Instantly-batch.

## Samenwerking

- **Instantly** kan kandidaatleads en geverifieerde contactdata aanleveren en later campagneverzending/follow-ups uitvoeren.
- **Leads + ChatGPT** bepalen leadfit, controleren de officiële website, kiezen één aantoonbaar verbeterpunt en maken de personalisatie.
- **Leadscanner** levert alleen ontbrekend technisch browserbewijs wanneer Leads dat nodig heeft.
- Scannerbevindingen veranderen nooit zelfstandig leadfit, prioriteit, compliance, verzendtoestemming of outreachstatus.

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

De scanner levert technische/browserobservaties. Hij bepaalt geen leadgeschiktheid, Leadscore, prioriteit, verzendgrond, conversiewinst, WCAG-conformiteit, Instantly-campaignstatus of productiegeschiktheid.
