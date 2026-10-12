# Leadscanner

**Bedrijven zoeken → websites onderzoeken → e-mailadres controleren → persoonlijke mail schrijven → concept in mijn.host bewaren.**

Geen campagnesoftware en geen automatische verzending. Je bekijkt de concepten in mijn.host en beslist zelf of verzenden passend en toegestaan is.

## Starten

Open [GitHub Actions — Leadscanner](../../actions/workflows/leads-cold.yml), kies Run workflow en vul regio en branches in.

| Modus | Wat gebeurt er? | Toegang |
| --- | --- | --- |
| **public_audit** | Onderzoek en mailkwaliteit testen, uitsluitend anonieme aantallen | Openbare repository mogelijk |
| **drafts** | Onderzoek, veilige concepten in mijn.host en dedupe-readback | **Uitsluitend handmatig op `main`**, geheimen blijven in Actions Secrets |
| **smoke** | Tijdelijk concept aan de eigen mailbox; exact teruglezen en verwijderen | Handmatig op `main`, zonder prospects of verzending |

**Keuze:** de GitHub-repository blijft openbaar. De `drafts`-actie mag daarom uitsluitend handmatig op `main` draaien, nooit vanuit pull requests of automatische pushes. De run toont alleen aantallen, bevat geen prospect-artifacts en verstuurt geen e-mails. Openbare Actions-logs vragen wel extra voorzichtigheid bij eigen wijzigingen.

### Beveiligd dedupe-register (vereist voor alle echte runs)
- Alle oude contactgegevens worden uitsluitend via de **Google Sheets API met OAuth read-only scope** opgehaald. De openbare CSV-exportlink is niet meer in de actieve workflow aanwezig.
- GitHub Secret: `LEAD_REGISTRY_SERVICE_ACCOUNT_JSON` (of `GOOGLE_SERVICE_ACCOUNT_JSON`), met toegang tot het bestaande Google Sheet. Openbare audit-runs gebruiken alleen een token met leesrechten.
- **Bestaande keuze:** het Google Sheet blijft *Iedereen met de link — Lezer*. Die toestemming geeft linkhouders toegang tot bestaande contact-/uitsluitgegevens. De code gebruikt desondanks alleen geauthenticeerde API-uitlezing en publiceert geen prospectinformatie in GitHub.
- De oorspronkelijke lijst mag niet worden gewist of vervangen. Het extra tabblad `HistoricalHmac` bevat alleen cryptografisch afgeschermde contactidentiteiten; de gewone uitsluitingen en hun opt-outs blijven actief.

### Benodigde GitHub Secrets voor mijn.host-drafts en smoke
- `OUTREACH_MAIL_PASSWORD` — wachtwoord van de mijn.host-mailbox.
- De bovengenoemde Google service-accountsecret is nodig om na exacte IMAP-teruglezing een concept in de registry vast te leggen. De aparte `smoke`-test gebruikt alleen IMAP en wijzigt het register niet.

Optionele GitHub Variables: OUTREACH_IMAP_HOST, OUTREACH_IMAP_PORT, OUTREACH_MAIL_USER, OUTREACH_SENDER_NAME, OUTREACH_SENDER_EMAIL en OUTREACH_DRAFT_FOLDER.

IMAP gebruikt beveiligde verbinding en poort 993. Er is **geen SMTP-verzendfunctie** en er worden geen persoonsgegevens als GitHub-artifact geüpload.

## Eén eenvoudige route

1. Bedrijven met website vinden via PDOK/Overture.
2. Oude contacten/bedrijven/domeinen uitsluiten met het dedupe-register.
3. Officiële websites en maximaal twaalf relevante interne pagina's onderzoeken, ook zonder e-mailadres.
4. Een daadwerkelijk gepubliceerd contact van eigenaar/medewerker controleren, anders zakelijk algemeen adres.
5. Maximaal zes echt onderbouwde observaties selecteren; een opvallend onderdeel is niet automatisch een probleem.
6. Eén korte Nederlandstalige of Engelstalige e-mail schrijven met een concreet sitefeit, één voorstel en één vraag. Inhoud automatisch valideren.
7. Dedupe opnieuw controleren, een mijn.host Draft aanmaken en exact teruglezen.
8. Pas na succesvolle opslag het contact in de dedupe-registratie vastleggen. Concepten blijven ter menselijke beoordeling.

Zonder bron, geldig contact, goede mail of nieuwe identiteit ontstaat geen draft. Bestaande gewijzigde drafts worden niet overschreven.

## Privacy, toestemming en historisch werk

Openbare runs tonen alleen cijfers. Handmatig vertrouwde Actions-runs verwerken adressen en concepten in afgeschermd runnergeheugen en mijn.host. Geen SMTP, geen verzendschema's.

Een gepubliceerd zakelijk e-mailadres of een opgeslagen concept is **geen toestemming om reclame te mailen**. De gebruiker beslist afzonderlijk en moet de toepasselijke regels en opt-outs controleren.

**Historische uitsluitingen (12 oktober 2026):** alle **1.128** oorspronkelijke e-mailidentiteiten blijven beschermd. Het nieuwe `HistoricalHmacV2`-tabblad van het gedeelde Google Sheet bevat uitsluitend keyed HMAC-SHA256-waarden: **914 geverifieerde officiële domeinen**, **146 voorzichtig afgeleide zakelijke maildomeinen**, en **68 contacten die alleen via het bestaande exacte e-mailadres zijn afgedekt**. Een domein van een zakelijke e-mail is geen hard bewijs van een bedrijfswebsite; daarom heet dit expliciet een conservatieve, aparte fallback.

De HMAC-sleutel staat nu **niet** in GitHub of het openbare register en is **niet meer afgeleid van de Google-serviceaccountprivatekey**. Hij wordt uit een onafhankelijk, privé gedeeld [sleutelkluisbestand](https://docs.google.com/spreadsheets/d/1wgSYVjxoetEg9v7N3F6s1_43UGDHEHET1F02vdMqas4/edit) geladen. Deze sleutelkluis is uitsluitend gedeeld met de eigenaar en de huidige serviceaccount. Vervanging van het Google-serviceaccount vereist wel dat de nieuwe account toegang tot deze privékluis en het openbare register krijgt; **de 1.128 tokens hoeven dan niet opnieuw te worden opgebouwd**. Als de cryptografische kluissleutel zelf wordt vervangen, is een afzonderlijk gecontroleerd nieuw-keyproces nodig. Ontbrekende, dubbele of gewijzigde sleutel-/HMAC-gegevens blokkeren Leadscanner veilig.

De oorspronkelijke 635 regels in `DedupeRegistry` en de oudere `HistoricalHmac`-registratie blijven onaangeroerd als historische bron. De eenmalige migratiecode en oude providerlogica zijn weer verwijderd. Er zijn geen e-mails verstuurd.

Lees [mailkwaliteit](docs/mailkwaliteit.md) en [technische regels](AGENTS.md).
