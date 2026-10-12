# Leadscanner — repository contract

## Eén workflow
De actieve route is **bedrijven vinden → officiële website onderzoeken → contactbron verifiëren → specifieke kansen kiezen → korte NL/EN-conceptmail valideren → als Draft in mijn.host bewaren → exact teruglezen → dedupe registreren**.

Geen campagnedienst, geen sequencebeheer, geen automatische verzending en geen SMTP-code.

## Twee uitvoermodi
- **public_audit:** ook in een openbare repository. Live onderzoek met uitsluitend geanonimiseerde aantallen. Geen ontvangers, concepten, bron-URL's, hashes of artifacts publiceren.
- **drafts:** één complete run van onderzoek tot gecontroleerde mijn.host-concepten. **Alleen privé**, met IMAP- en registry-credentials in GitHub Secrets. De gebruiker beoordeelt de Drafts zelf; er wordt niet verzonden.

Verander de repositoryzichtbaarheid nooit zonder toestemming.

## Kernregels
- Het bestaande Google Sheet Lead Dedupe Registry is de historische uitsluitingsbron. Lees het **uitsluitend via de geauthenticeerde Sheets API met read-only OAuth scope**, nooit via openbaar CSV-export of een lokale kopie. Controleer bedrijfsnaam, domein, adres en lead-ID vóór onderzoek en direct vóór mailboxwijziging. Eerdere verzendingen, reacties, bounces, opt-outs en concepten blijven uitgesloten.
- E-mail is nooit vereist voor websiteonderzoek. Verifieer de identiteit, bezoek maximaal twaalf veilige officiële vervolgpagina's en zoek pas daarna een werkelijk gepubliceerd e-mailadres. Eigenaar/medewerker eerst, anders algemeen zakelijk adres. Nooit adressen raden.
- Maximaal zes concrete, onafhankelijke eerstehands bevindingen. Een opvallend onderdeel is niet automatisch een fout. Geen verzonnen tekortkomingen, resultaten, testimonials, prijzen of rendement.
- Eén korte NL/EN-mail met verifieerbaar sitefeit, één klein voorgesteld voorbeeld en één vriendelijke vraag. De kwaliteitsvalidator bepaalt of het concept geschikt is. Zonder bewijs of contact wordt geen concept opgeslagen.
- Status review_draft betekent dat een mens het concept beoordeelt. Een concept is geen toestemming om reclame te versturen.
- Sla uitsluitend via beveiligde IMAP op in Drafts; controleer UID, \\Draft-flag, **From**, ontvanger, onderwerp, body en status exact. Vervang gewijzigde concepten nooit automatisch. Bij onzekere uitkomst geen blinde herhaling.
- Registreer in de dedupe-registry pas na bewezen IMAP-readback.
- Geen SMTP, geplande verzendingen, automatische follow-ups, campagnes of activatie.
- Alle invoer en requests begrenzen, veilige URL's afdwingen en geen gevoelige logs of artifacts maken.

## Ontwikkeling
- Werk richting actuele main via controleerbare PR en geslaagde tests. Bouw geen tweede pipeline.
- Test contracten, bron-/contactkwaliteit, dedupe, privacy, IMAP-idempotentie, exacte registry-readback en fail-closed gevallen.
- CI zonder echte IMAP is geen live bewijs; claim daadwerkelijke conceptopslag alleen na afgeschermde IMAP-readback.
- Historische gegevens in andere diensten worden niet door repositorywijzigingen verwijderd of automatisch gemigreerd.

## Releaseblokkers

- Revoke de Google Drive-machtiging **Iedereen met de link** voor het canonieke register. Hiervoor bestaat nu geen aangesloten permission-delete-actie; dit vereist een expliciete handeling in de Google Drive UI.
- Een live mijn.host-IMAP test vereist een privé-GitHub-repository en geldige secrets. Synthetische tests of openbare website-audits mogen nooit als live IMAP-bewijs worden gepresenteerd.
- Nog geen complete externe reconciliation van alle historische Instantly-contacten met de retained registry; introduceer geen tweede pipeline.
