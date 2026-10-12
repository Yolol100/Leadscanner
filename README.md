# Leadscanner

**Bedrijven zoeken → websites onderzoeken → e-mailadres controleren → persoonlijke mail schrijven → concept in mijn.host bewaren.**

Geen campagnesoftware en geen automatische verzending. Je bekijkt de concepten in mijn.host en beslist zelf of verzenden passend en toegestaan is.

## Starten

Open [GitHub Actions — Leadscanner](../../actions/workflows/leads-cold.yml), kies Run workflow en vul regio en branches in.

| Modus | Wat gebeurt er? | Toegang |
| --- | --- | --- |
| **public_audit** | Onderzoek en mailkwaliteit testen, uitsluitend anonieme aantallen | Openbare repository mogelijk |
| **drafts** | Onderzoek plus gecontroleerde concepten in mijn.host | **Privé-repository vereist** |

**Belangrijk:** de repository is momenteel openbaar. Zet deze eerst privé via GitHub Settings → General → Change repository visibility voor echte concepten. Dit wordt niet automatisch gewijzigd.

### Beveiligd dedupe-register (vereist voor alle echte runs)
- Alle oude contactgegevens worden uitsluitend via de **Google Sheets API met OAuth read-only scope** opgehaald. De openbare CSV-exportlink is niet meer in de actieve workflow aanwezig.
- GitHub Secret: `LEAD_REGISTRY_SERVICE_ACCOUNT_JSON` (of `GOOGLE_SERVICE_ACCOUNT_JSON`), met toegang tot het bestaande Google Sheet. Openbare audit-runs gebruiken alleen een token met leesrechten.
- **Open privacyactie:** in Google Drive bij **Lead Dedupe Registry → Delen → Algemene toegang** moet *Iedereen met de link* naar *Beperkt* worden gewijzigd. Dit is nog niet uitgevoerd. De repo alleen privé maken trekt de oude link niet in.
- De historische lijst mag niet worden gewist of vervangen; eerdere contacten, reacties, bounces en opt-outs blijven uitgesloten.

### Benodigde GitHub Secrets voor mijn.host-drafts
- `OUTREACH_MAIL_PASSWORD` — wachtwoord van de mijn.host-mailbox.
- De bovengenoemde Google service-accountsecret is ook nodig om na exacte IMAP-teruglezing een concept in de registry vast te leggen.

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

Openbare runs tonen alleen cijfers. Privé-runs verwerken adressen en concepten in afgeschermd runnergeheugen en mijn.host. Geen SMTP, geen verzendschema's.

Een gepubliceerd zakelijk e-mailadres of een opgeslagen concept is **geen toestemming om reclame te mailen**. De gebruiker beslist afzonderlijk en moet de toepasselijke regels en opt-outs controleren.

De eerdere contacten in een externe campagnedienst worden niet verwijderd of gemigreerd door deze codewijziging. Het uitsluitregister blijft behouden, maar volledige dekking van alle historische contact-ID's is nog niet extern bevestigd. Voor oude, nog niet in mijn.host opgeslagen concepten is een afzonderlijk afgeschermd export/import-traject nodig.

Lees [mailkwaliteit](docs/mailkwaliteit.md) en [technische regels](AGENTS.md).
