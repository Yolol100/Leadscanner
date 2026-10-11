# Leadscanner

Leadscanner onderzoekt bedrijfswebsites en webshops, selecteert controleerbare bevindingen en maakt **concepten ter beoordeling**. De gebruiker hoeft niet met de tientallen technische tussenstappen te werken.

**Kort gezegd: zoeken → onderzoeken → kiezen → beoordelen.** Niets wordt automatisch verzonden.

**Privacybeperking (11 oktober 2026):** deze repository is momenteel **openbaar**. De
**persoonlijke preview met contactgegevens en conceptmails**, het opslaan van
mailboxconcepten en Instantly-staging blijven geblokkeerd totdat de repository
**privé** is. De afzonderlijke `public_audit` mag wel publieke websites lezen
en alleen geanonimiseerde tellingen rapporteren. De reviewbestanden
bevatten zakelijke contactadressen en persoonlijke conceptteksten; deze horen
niet in publiek downloadbare GitHub Actions-artifacts.

**Oude artifact-opslag gecontroleerd (11 oktober 2026):** tijdens drie eenmalige
Actions-opschonings-/verificatieruns zijn 105 artifacts verwijderd (waaronder
tijdelijke controlerapporten uit die runs). Bij de laatste API-readback bleven
40 artifacts over; allemaal met een expliciet toegelaten naam voor
geanonimiseerde site-research- of Instantly-sync-tellingen. Volgens die
inventaris bleven 0 verdachte of niet-geclassificeerde artifacts over.
Zie [het technische auditbewijs](docs/operations/artifact-cleanup-and-smoke-20261011.md).

Deze opschoning verwijdert **geen oude Actions-logs** of externe kopieën die
mogelijk al zijn gedownload; die moeten zo nodig afzonderlijk worden
beoordeeld. Maak de repository privé via GitHub Settings > General >
Danger Zone > Change repository visibility voordat een persoonlijke preview met bewaarde contactgegevens,
Instantly-staging of mijn.host-conceptopslag wordt uitgevoerd.


## De vier stappen

| Stap | Wat gebeurt er? | Wat zie je? |
| --- | --- | --- |
| 1. Zoeken | Vind bedrijven met een publieke website, controleer bestaande uitsluitingen en bevestig de site. **Een e-mailadres is hier niet vereist.** | Aantal vindbare websites |
| 2. Onderzoeken | Bekijk de homepage en maximaal twaalf extra bereikbare publieke pagina's; onderzoek eerst Over ons, Team, Eigenaar en Contact, daarna diensten, producten en andere kansen. Vind pas daarna het beste gepubliceerd e-mailadres. | Websiteobservaties, persoon + e-mailbron indien gevonden |
| 3. Kiezen | Deel opvallende feiten in categorieën in, rangschik ze en neem de **maximaal zes belangrijkste onderbouwde punten** voor de review (hoogstens drie als korte, letterlijk onderbouwde highlights in de conceptmail) mee. Herhaal hetzelfde onderwerp niet meer dan twee keer en vul een sterke selectie niet met zwakke opmerkingen. Minder als er minder bewijs is. | Prioriteit, categorie, observatie, bron |
| 4. Beoordelen | Kies eerst een aantoonbaar persoonlijk adres van eigenaar/team, anders een gepubliceerd algemeen adres (ook via externe mailprovider). Zonder adres blijft het websiteonderzoek geldig, maar ontstaat geen geadresseerde conceptmail. | Openbare `public_audit`: alleen tellingen; privé `preview`: review-queue en tokens |

Een observatie is niet automatisch een bewezen probleem. Leadscanner mag geen gebreken, resultaten of omzetverbeteringen verzinnen. Algemene reclamezinnen zijn onvoldoende onderbouwing. De scanner volgt ook relevante interne vervolgpagina's binnen het vaste paginabudget. Een korte zin met onduidelijke taal kan alleen via extra, officiële site-inhoud worden geduid. Publieke tellingen tonen uitsluitend bekende statuscategorieën, nooit vrije website- of prospectteksten.

## Aan de slag

Gebruik [GitHub Actions — Leads Cold Pipeline](../../actions/workflows/leads-cold.yml) en kies **Run workflow** op `main`.

- **`public_audit` (standaard, werkt in openbare repository):** live websiteonderzoek met maximaal 60 bedrijven, de bestaande dedupecontrole, eigenaar-/team-/contactpagina's, prioritering en conceptvalidatie. De inhoud blijft tijdelijk in werkgeheugen; alleen geanonimiseerde tellingen worden gepubliceerd. Niemand wordt gemaild, goedgekeurd of gestaged.
- **`preview` (alleen in een privé-repository):** onderzoek en maak een review-overzicht; geen wijzigingen in mailbox, Instantly of de deduplicatieregistratie. `preview_copy_mode=reviewed_mail` is de **default** en maakt een korte Nederlandstalige of Engelstalige conceptmail. Met `preview_copy_mode=instantly_sequence` exporteer je alleen gecontroleerde feiten, zonder conceptmail.
- **`instantly_stage`:** zet **expliciet goedgekeurde** contacten klaar in een toegestane Draft/Paused Instantly-campagne. Vereist het oorspronkelijke `preview_run_id`, exacte `approved_review_tokens`, een campagne-ID en bevestiging. De campagne wordt **niet geactiveerd**.
- **`draft`:** optionele fallback voor concepten in mijn.host. Ook dit vereist een exacte eerdere preview, goedkeuring en bevestiging. Fact-only records kunnen niet als mailboxconcept worden opgeslagen.

De **eerste output** die je als gebruiker nodig hebt, is `overzicht.md` in het run-artifact en in de GitHub job summary. Dit bevat alleen totalen en uitleg, geen adressen of prospecttekst. Voor afzonderlijke kandidaten open je `review-queue.md` (met de gerangschikte bevindingen en bronnen) of de CSV. Geavanceerde JSON-bestanden zijn voor controle en herstel bedoeld, niet voor dagelijks gebruik.

## Waarom gaat iets op hold?

Een bedrijf wordt niet automatisch geschikt omdat het een website heeft. Mogelijke oorzaken:

- Bedrijf al bekend, onderdrukt of eerder onderzocht; nooit blind opnieuw benaderen.
- Geen gepubliceerd e-mailadres: **websiteonderzoek gaat gewoon door**. Publiek gepubliceerde zakelijke e-mails in bij het bedrijf passende schema.org JSON-LD tellen ook mee wanneer de koppeling met het bedrijf bevestigd is. Een expliciet vermelde persoon uit dezelfde bedrijfsgegevens krijgt alleen voorrang als diens werkgever en eigen e-mailadres controleerbaar aan het bedrijf zijn gekoppeld. Een aantoonbaar contactformulier, telefoonlink of bezochte Contact-pagina wordt apart geregistreerd. Een Contact-pagina bewijst niet dat het formulier werkt; geen van deze routes is een e-mailadres en niets wordt automatisch gebruikt. Een geadresseerde conceptmail blijft achterwege.
- Een geverifieerde website telt als onderzocht na bezoek, ook zonder voldoende concrete observaties. De kwaliteitsmeting telt bruikbaar bewijs **apart**; geen geforceerde bevindingen om een hoog cijfer te halen.
- De openbare onderzoeksrun toont aparte **anonieme** aantallen voor bezochte sites, bruikbaar bewijs, gevonden e-mailadressen, contactformulieren, telefoonlinks en contactpagina's. Een gevonden contactroute is niet hetzelfde als een geverifieerd e-mailadres of een goedgekeurd concept.
- Website onbereikbaar of robots-/domeinveiligheid laat lezen niet toe. Bij een verouderde URL probeert de scanner maximaal twee veilige alternatieven op hetzelfde domein; robots- of toegangswigeringen worden nooit omzeild.
- Geen concrete, controleerbare observatie of geen betrouwbare taalherkenning.
- Concept of broncontrole voldoet niet aan het contract.

De privacyveilige `funnel-metrics.json` bevat aantallen per reden. De gebruiksvriendelijke `overzicht.md` toont de belangrijkste groepen. Houd- of afwijsregels worden **niet** versoepeld door het uiterlijk eenvoudiger te maken.

## Veiligheid, goedkeuring en verzending

**Preview ≠ goedkeuring ≠ staging ≠ verzending.** Alle vier zijn gescheiden.

1. Dedupe-controle gebeurt vóór websiteonderzoek en opnieuw direct vóór staging. De Google Sheet Lead Dedupe Registry is alleen voor uitsluiting, niet als onderzoeksbron.
2. Verifieer eerst de officiële website, ongeacht e-mail. Onderzoek die site breed. Zoek daarna een gepubliceerd adres met voorrang voor een aantoonbaar genoemde eigenaar of teamlid. Algemene adressen zijn fallback; een persoonlijk adres wordt nooit geraden. Bron-URL's, contactidentiteit en observaties blijven aan review en goedkeuring gekoppeld.
3. Review-tokens en preview-snapshots worden aan de inhoud gebonden. Aangepaste of verouderde bronnen/tekst vereisen een nieuwe goedkeuring.
4. Instantly-staging vereist exacte autorisatie, campagnecontrole, geldige mergevelden en succesvolle readback. Fact-only templates vereisen bovendien een afzonderlijk goedgekeurde **Draft-campagne met precies drie e-mailstappen**.
5. **Verzenden/activeren is een aparte handeling** en vereist een aantoonbare contact-/toestemmingsgrondslag per lead, ontvanger- en campagnecontroles en nieuwe expliciete bevestiging. Een publiek zakelijk e-mailadres is **geen toestemming**.
6. Achtergrondreconciliatie leest Instantly en werkt alleen bekende registratieregels bij; maakt geen leads of verzendingen.

Bij een mislukte veiligheidscontrole stopt de betreffende mutatie. Er worden geen contactgegevens of e-mailinhoud geplaatst in publieke status- of controlebestanden.

## Technische indeling

| Onderdeel | Bestand(en) | Verantwoordelijkheid |
| --- | --- | --- |
| Discovery/dedupe | `overture_discovery.py`, `dedupe_preflight.py` | Nieuwe kandidaten, bestaande uitsluitingen |
| Website + contact | `cold_stages.py`, `first_party_contacts.py`, `instantly_site_crawl.py` | Eerst officiële site onderzoeken, daarna benoemde eigenaar of algemeen contact vinden |
| Prioriteiten + copy | `outreach_stages.py` | Eén gedeelde selectie- en conceptlogica, ook voor historisch onderzoek |
| Review | `review_draft_stages.py`, `review_selection.py`, `preview_snapshot.py` | Kandidaten, bronlijst, onwijzigbare goedkeuringen |
| Kort overzicht | `simple_overview.py` | Eén leesbaar, geanonimiseerd run-overzicht |
| Instantly | `instantly_client.py`, `instantly_service.py`, `instantly_control.py` | Alleen uitdrukkelijk toegestane API-acties, exacte controles |
| Status/kwaliteit | `funnel_metrics.py`, `coverage_audit.py`, `cold_run_manifest.py`, `instantly_audit.py` | Cijfers, audit en uitvoerbewijs |

De instap is eenvoudig gehouden; de harde veiligheidscontroles blijven bewust expliciet in de code. Voor ontwikkelregels en exacte campagnevoorwaarden: [AGENTS.md](AGENTS.md). Voor historische technische audits en migratieachtergrond: [docs/](docs/).

Het losse historisch Instantly-websiteonderzoek gebruikt `.github/workflows/historical-site-research.yml` en bewaart alleen reviewvoorstellen; codewijzigingen starten niet automatisch een volledige nieuwe historische scan. Bestaande beoordeelde of verzonden contacten blijven beschermd.
