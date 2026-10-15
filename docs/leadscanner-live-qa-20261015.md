# Live QA - snelle en veilige Webactueel Leads-research (15 oktober 2026)

Bewijsbron: GitHub Actions run 38813849977 (main commit d7da537552170b109fefb0574af3f2a38f452e00), plus gecontroleerde headers/statussen in het privé Google Sheet. Geen bedrijfsnamen, e-mailadressen of correspondentie in deze openbare rapportage.

## Eerste geforceerde hercontrole (zonder mailwrites)
- 57 bestaande officieel geregistreerde bedrijven onderzocht
- 57 websitechecks, 0 geldige cachehits (bewust geforceerd)
- 46 met `verified_*`, 11 `needs_manual_check`
- Na branchegerichte uitbreiding 22 status `verified_with_detail`
- 21 uitsluitend inhoudelijke kandidaten vóór deduplicatie/redactionele/juridische toets, waarvan 11 met officieel geverifieerde HTTP-website
- Totale onderzoekstijd: 32,14 s; p50 2.508 ms, p95 6.294 ms per website
- 0 IMAP-writes en 0 verzendingen

Dit zijn bron-/code- en runtimecijfers, geen conversiepercentages of verzendtoestemming. De 450 bestaande mails blijven een aparte, niet geraakte workflow.

## Regressies
GitHub Actions PR #1696: 309/309 volledige tests geslaagd en gerichte websitecontroles geslaagd vóór squash naar main. Nieuwe tests: HTTP-adressen, branche-/dienstfeiten, cacheproof, privé read-only audit, gewijzigde conceptinhoud bij retry, schema's en minimale Python-dependencies.

## Tweede controle
De volgende expliciet gelabelde `LEADS_CACHE_SMOKE:`-push test een echte tweede verwerking met geldige positieve broncache. Registreer de uitkomst pas na exacte GitHub-run- en privétabblad-readback. Een groene run alleen is niet voldoende.

Veiligheid: geen SMTP, geen automatisch verzenden, geen publieke prospectdata, geen wijziging van Review450, geen reset van dedupe/HMAC/opt-outs.