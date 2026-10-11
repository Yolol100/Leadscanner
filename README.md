# Leadscanner

Leadscanner onderzoekt bedrijfswebsites en webshops, selecteert controleerbare bevindingen en maakt **concepten ter beoordeling**. De gebruiker hoeft niet met de tientallen technische tussenstappen te werken.

**Kort gezegd: zoeken → onderzoeken → kiezen → beoordelen.** Niets wordt automatisch verzonden.

## De vier stappen

| Stap | Wat gebeurt er? | Wat zie je? |
| --- | --- | --- |
| 1. Zoeken | Vind bedrijven met website. Controleer de bestaande deduplicatieregistratie en bevestig de officiële site en het zakelijke contactadres. | Hoeveel bedrijven overblijven |
| 2. Onderzoeken | Bekijk de homepage en maximaal twaalf extra publieke pagina's van hetzelfde domein; alleen waar de website en robotsregels dit toestaan. | Controleerbare observaties met bron-URL |
| 3. Kiezen | Deel opvallende feiten in categorieën in, rangschik ze en neem de **maximaal zes belangrijkste onderbouwde punten** mee. Minder als er minder bewijs is. | Prioriteit, categorie, observatie, bron |
| 4. Beoordelen | Maak een compacte persoonlijke conceptmail, of kies bewust de feiten-voor-template-route. De gebruiker beoordeelt en keurt precies die inhoud goed. | `overzicht.md`, `review-queue.md`, review-CSV, goedkeuringstokens |

Een observatie is niet automatisch een bewezen probleem. Leadscanner mag geen gebreken, resultaten of omzetverbeteringen verzinnen. Algemene reclamezinnen zijn onvoldoende onderbouwing.

## Aan de slag

Gebruik [GitHub Actions — Leads Cold Pipeline](../../actions/workflows/leads-cold.yml) en kies **Run workflow** op `main`.

- **`preview` (standaard):** onderzoek en maak een review-overzicht; geen wijzigingen in mailbox, Instantly of de deduplicatieregistratie. `preview_copy_mode=reviewed_mail` is de **default** en maakt een korte Nederlandstalige of Engelstalige conceptmail. Met `preview_copy_mode=instantly_sequence` exporteer je alleen gecontroleerde feiten, zonder conceptmail.
- **`instantly_stage`:** zet **expliciet goedgekeurde** contacten klaar in een toegestane Draft/Paused Instantly-campagne. Vereist het oorspronkelijke `preview_run_id`, exacte `approved_review_tokens`, een campagne-ID en bevestiging. De campagne wordt **niet geactiveerd**.
- **`draft`:** optionele fallback voor concepten in mijn.host. Ook dit vereist een exacte eerdere preview, goedkeuring en bevestiging. Fact-only records kunnen niet als mailboxconcept worden opgeslagen.

De **eerste output** die je als gebruiker nodig hebt, is `overzicht.md` in het run-artifact en in de GitHub job summary. Dit bevat alleen totalen en uitleg, geen adressen of prospecttekst. Voor afzonderlijke kandidaten open je `review-queue.md` (met de gerangschikte bevindingen en bronnen) of de CSV. Geavanceerde JSON-bestanden zijn voor controle en herstel bedoeld, niet voor dagelijks gebruik.

## Waarom gaat iets op hold?

Een bedrijf wordt niet automatisch geschikt omdat het een website heeft. Mogelijke oorzaken:

- Bedrijf al bekend, onderdrukt of eerder onderzocht; nooit blind opnieuw benaderen.
- Zakelijk e-mailadres niet verifieerbaar op de officiële website.
- Website onbereikbaar of robots-/domeinveiligheid laat lezen niet toe.
- Geen concrete, controleerbare observatie of geen betrouwbare taalherkenning.
- Concept of broncontrole voldoet niet aan het contract.

De privacyveilige `funnel-metrics.json` bevat aantallen per reden. De gebruiksvriendelijke `overzicht.md` toont de belangrijkste groepen. Houd- of afwijsregels worden **niet** versoepeld door het uiterlijk eenvoudiger te maken.

## Veiligheid, goedkeuring en verzending

**Preview ≠ goedkeuring ≠ staging ≠ verzending.** Alle vier zijn gescheiden.

1. Dedupe-controle gebeurt vóór websiteonderzoek en opnieuw direct vóór staging. De Google Sheet Lead Dedupe Registry is alleen voor uitsluiting, niet als onderzoeksbron.
2. De website en het gepubliceerde zakelijke adres moeten aantoonbaar bij het bedrijf horen. Bron-URL's en elke geselecteerde observatie blijven verbonden aan de review en het exacte goedkeuringstoken.
3. Review-tokens en preview-snapshots worden aan de inhoud gebonden. Aangepaste of verouderde bronnen/tekst vereisen een nieuwe goedkeuring.
4. Instantly-staging vereist exacte autorisatie, campagnecontrole, geldige mergevelden en succesvolle readback. Fact-only templates vereisen bovendien een afzonderlijk goedgekeurde **Draft-campagne met precies drie e-mailstappen**.
5. **Verzenden/activeren is een aparte handeling** en vereist een aantoonbare contact-/toestemmingsgrondslag per lead, ontvanger- en campagnecontroles en nieuwe expliciete bevestiging. Een publiek zakelijk e-mailadres is **geen toestemming**.
6. Achtergrondreconciliatie leest Instantly en werkt alleen bekende registratieregels bij; maakt geen leads of verzendingen.

Bij een mislukte veiligheidscontrole stopt de betreffende mutatie. Er worden geen contactgegevens of e-mailinhoud geplaatst in publieke status- of controlebestanden.

## Technische indeling

| Onderdeel | Bestand(en) | Verantwoordelijkheid |
| --- | --- | --- |
| Discovery/dedupe | `overture_discovery.py`, `dedupe_preflight.py` | Nieuwe kandidaten, bestaande uitsluitingen |
| Website | `cold_stages.py`, `instantly_site_crawl.py` | Verifiëren en beperkt publiek onderzoek |
| Prioriteiten + copy | `outreach_stages.py` | Eén gedeelde selectie- en conceptlogica, ook voor historisch onderzoek |
| Review | `review_draft_stages.py`, `review_selection.py`, `preview_snapshot.py` | Kandidaten, bronlijst, onwijzigbare goedkeuringen |
| Kort overzicht | `simple_overview.py` | Eén leesbaar, geanonimiseerd run-overzicht |
| Instantly | `instantly_client.py`, `instantly_service.py`, `instantly_control.py` | Alleen uitdrukkelijk toegestane API-acties, exacte controles |
| Status/kwaliteit | `funnel_metrics.py`, `coverage_audit.py`, `cold_run_manifest.py`, `instantly_audit.py` | Cijfers, audit en uitvoerbewijs |

De instap is eenvoudig gehouden; de harde veiligheidscontroles blijven bewust expliciet in de code. Voor ontwikkelregels en exacte campagnevoorwaarden: [AGENTS.md](AGENTS.md). Voor historische technische audits en migratieachtergrond: [docs/](docs/).

Het losse historisch Instantly-websiteonderzoek gebruikt `.github/workflows/historical-site-research.yml` en bewaart alleen reviewvoorstellen; codewijzigingen starten niet automatisch een volledige nieuwe historische scan. Bestaande beoordeelde of verzonden contacten blijven beschermd.
