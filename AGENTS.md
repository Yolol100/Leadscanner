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
- Sla uitsluitend via beveiligde IMAP op in Drafts; controleer UID, \\Draft-flag, **From**, ontvanger, onderwerp, body en status exact. Herschrijf bestaande concepten alleen na expliciete gebruikersopdracht, originele-websitecontrole, brongebonden contactcheck en UID-specifieke beveiligde vervanging met exact readback. In de bestaande-only herschrijfmodus mogen onderwerp, inhoud en reviewstatus veranderen, maar nooit de geverifieerde ontvanger of een ontbrekend concept worden aangemaakt. Bij onzekere uitkomst geen blinde herhaling.
- Registreer in de dedupe-registry pas na bewezen IMAP-readback.
- Geen SMTP, geplande verzendingen, automatische follow-ups, campagnes of activatie.
- Alle invoer en requests begrenzen, veilige URL's afdwingen en geen gevoelige logs of artifacts maken.

## Ontwikkeling
- Werk richting actuele main via controleerbare PR en geslaagde tests. Bouw geen tweede pipeline.
- Test contracten, bron-/contactkwaliteit, dedupe, privacy, IMAP-idempotentie, exacte registry-readback en fail-closed gevallen.
- CI zonder echte IMAP is geen live bewijs; claim daadwerkelijke conceptopslag alleen na afgeschermde IMAP-readback.
- Historische gegevens in andere diensten worden niet door repositorywijzigingen verwijderd of automatisch gemigreerd.

## Historische uitsluitingen en sleutelbeheer

- Normale workflow leest het oorspronkelijke `DedupeRegistry` én `HistoricalHmacV2` uit de publieke Google Sheet. Het sleutelgeheim zit **alleen** in de apart, privé gedeelde Google Sheets-kluis `Leadscanner HMAC Key Vault - PRIVATE` (tab `Keys`). Niet kopiëren naar repository, openbare logs of publieke Sheets.
- HMAC v2 dekt alle **1.128** bron-e-mailidentiteiten, **914 geverifieerde officiële bedrijfsdomeinen** en **146 conservatief afgeleide, niet-gedeelde zakelijke e-maildomeinen**. Voor **68** historische adressen bij gedeelde providers is alleen de exacte e-mailidentiteit bewezen; noem die niet bedrijf-breed afgedekt.
- Verifieer bij iedere start exact de vaultkey, alle 1.128 geldige unieke records en de verdeling 914/146/68. Bij ontbrekende kluis, verkeerde sleutel of incompleet tabblad: **stop vóór bedrijfsresearch of mailboxwijziging**.
- Bij rotatie van het Google-serviceaccount: geef het **nieuwe account** eerst leesrechten op de aparte privékluis en het openbare register, verifieer live de volledige v2-dedupe, en trek daarna pas de toegang van de oude account in. Door de onafhankelijke sleutel blijft de hashdekking behouden; nooit eerst de oude toegang verbreken.
- Rotatie van de **HMAC-kluissleutel zelf** vereist een apart gecontroleerd twee-fasenplan met volledige bronreconciliatie voordat de vorige versie wordt uitgefaseerd. Draai niet blind een nieuwe random sleutel terwijl oude hashes actief zijn.
- De gebruiker heeft bewust gekozen voor een openbare repo en het bestaande openbaar gedeelde register; respecteer dit. Alleen keyed identiteiten zijn aan het openbare sheet toegevoegd. De oorspronkelijke 635 registraties zijn behouden.
- Alle historische provider-migratiecode is na eenmalig bewijs verwijderd; geen campagnedienst terugbrengen.

## Live verificatie
- Een geslaagde synthetische IMAP-self-test bewijst mailboxopslag, niet dat een specifieke prospectmail goedgekeurd is.
- Test nieuwe prospectconcepten uitsluitend na historische dedupe, bron-, contact- en mailkwaliteitchecks, met volledig veilige readback en handmatige beoordeling.
- Vergelijk voor volledigheid de historische contacten met de retained registry. Breng geen verwijderde campagnestroom terug als permanent onderdeel van Leadscanner.
