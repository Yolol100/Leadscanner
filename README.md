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

### Benodigde GitHub Secrets voor drafts
- OUTREACH_MAIL_PASSWORD — wachtwoord van de mijn.host-mailbox.
- LEAD_REGISTRY_SERVICE_ACCOUNT_JSON (of GOOGLE_SERVICE_ACCOUNT_JSON) — toegang voor dedupe-registratie.

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

De eerdere contacten in een externe campagnedienst worden niet verwijderd of gemigreerd door deze codewijziging. Het bestaande uitsluitregister blijft behouden. Voor oude, nog niet in mijn.host opgeslagen concepten is een afzonderlijk afgeschermd export/import-traject nodig.

Lees [mailkwaliteit](docs/mailkwaliteit.md) en [technische regels](AGENTS.md).
