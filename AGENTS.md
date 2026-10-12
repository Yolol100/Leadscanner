# Leadscanner — repository contract

## Eén workflow
De actieve route is **bedrijven vinden → officiële website onderzoeken → contactbron verifiëren → specifieke kansen kiezen → korte NL/EN-conceptmail valideren → als Draft in mijn.host bewaren → exact teruglezen → dedupe registreren**.

Geen campagnedienst, geen sequencebeheer, geen automatische verzending en geen SMTP-code.

## Twee uitvoermodi
- **public_audit:** ook in een openbare repository. Live onderzoek met uitsluitend geanonimiseerde aantallen. Geen ontvangers, concepten, bron-URL's, hashes of artifacts publiceren.
- **drafts:** uitsluitend expliciet handmatig via GitHub Actions op de `main`-branch, met secrets; geen data in openbare logs of artifacts. De gebruiker beoordeelt mijn.host Drafts zelf; er wordt niet verzonden.
- **smoke:** uitsluitend de eigen mailbox via IMAP, één synthetisch Draft, exacte verificatie en UID-specifieke verwijdering. Geen prospects, registry-mutaties of verzending.

De gebruiker heeft expliciet gekozen dat de repo openbaar blijft en dat het Google Sheet via de bestaande deellink leesbaar blijft. Respecteer dit; behandel zichtbaarheid als een bewust geaccepteerd risico en log nooit contactdata.

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

## Historische uitsluiting

Een eenmalige read-only providervergelijking toonde eerst 251/1.128 treffers. Daarna zijn **alle 1.128** broncontacten in batches van maximaal 100 met geheim-sleutel-HMAC in hetzelfde, openbaar gedeelde Google Sheet vastgelegd (tab `HistoricalHmac`). De exacte afgedekte e-mailidentiteiten zijn gecontroleerd op volledige 1.128/1.128 dekking. Daarnaast zijn 914 geverifieerde bedrijfsdomeinen gehasht. Er is geen plaintext broncontactinformatie aan het register toegevoegd.

- Voer **voor elk onderzoek** de bestaande openbare `DedupeRegistry` en de volledige `HistoricalHmac`-readback uit. De HMAC-tab en sleutelcontrole zijn verplicht: ontbrekend, onvolledig, gewijzigd of fout geheim → fail closed, geen nieuwe bedrijven verwerken.
- Gebruik alleen de service-accountprivatekey uit de bestaande Actions Secret voor de domein-gescheiden HMAC-afleiding. **Sleutelrotatie** maakt de oude tokens onbruikbaar: eerst een apart gecontroleerd her-sleutelproces, nooit stilzwijgend negeren of de beveiliging uitschakelen.
- De oorspronkelijke 635 uitsluitingen blijven behouden. Een e-mailadres dat vroeger is gebruikt wordt exact herkend; een ander adres bij hetzelfde bedrijf kan alleen worden geblokkeerd als het oude officiële domein geverifieerd was (914 gevallen), of als het al in het oorspronkelijke register voorkomt.
- De bronimportcode is na de live migratie verwijderd. Geen campagnedienst aan de permanente code toevoegen.

## Live verificatie
- Een geslaagde synthetische IMAP-self-test bewijst mailboxopslag, niet dat een specifieke prospectmail goedgekeurd is.
- Test nieuwe prospectconcepten uitsluitend na historische dedupe, bron-, contact- en mailkwaliteitchecks, met volledig veilige readback en handmatige beoordeling.
- Vergelijk voor volledigheid de historische contacten met de retained registry. Breng geen verwijderde campagnestroom terug als permanent onderdeel van Leadscanner.
