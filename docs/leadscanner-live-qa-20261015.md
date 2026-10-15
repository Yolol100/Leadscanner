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
## Tweede live check en aantoonbare cachewinst

GitHub Actions run [38814017280](https://github.com/Yolol100/Leadscanner/actions/runs/38814017280) (main commit `9a1a8e621202e36607bb4b13cf897be6773f8fb8`) heeft het privé `Approved`-snapshot opnieuw gecontroleerd. Van 57 records zijn **46 geldige positieve bronrecords hergebruikt** en **11 websites opnieuw gelezen**. Totale check: **16,35 s** in plaats van 32,14 s bij geforceerde eerste controle; ongeveer 49,1% korter binnen dit live voorbeeld (geen gegarandeerde snelheid voor toekomstige websites). Er zijn daarna 51 bevestigde activiteit-/detailbronnen, 6 met extra controle nodig, 26 specifieke `verified_with_detail`-records. De anonieme copy-QA vond 24 inhoudelijke kandidaten vóór dedupe en menselijke/juridische toets; 13 daarvan op eerder officieel geverifieerde HTTP-websites. **0 mailboxwrites en 0 verzendingen.**

## Laatste integratiecheck Mijn.Host

De metadata-only Sheets-canary was eerder geslaagd: run [38812220555](https://github.com/Yolol100/Leadscanner/actions/runs/38812220555), `private_state_ready`, exact schema in privé `AutoDraftState`. Een afzonderlijke, eenmalige `LEADS_AUTODRAFT_PREFLIGHT_ONLY:`-canary controleert nu ook IMAP-aanmelding, Drafts-folderidentificatie en **EXAMINE (uitsluitend read-only)** met bestaande Mijn.Host-geheimen. Deze controle gebruikt geen APPEND, geen FLAGS-wijziging, geen SELECT met schrijfrechten en geen SMTP. De definitieve live resultaatstatus wordt pas na exacte GitHub-job-readback geclaimd. De eerste geplande echte conceptbatch blijft zonder precedent totdat hij daadwerkelijk wordt uitgevoerd en ieder concept exact is teruggelezen.
