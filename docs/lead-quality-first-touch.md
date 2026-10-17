# Lead quality-first gate — optionele interne controle (2026-10-15)

Deze module verandert de **vier gebruikersstappen** niet: (1) bedrijf, (2) officieel e-mailadres, (3) concept naar privé Mijn.Host Drafts, (4) menselijke controle. `webactueel-workflow` blijft controller. Geen auditdienst, CRM, campagne, SMTP, verzending, tracking of follow-ups. Bestaande zes branchesjablonen zijn legacy/fallback en geen bewijs dat een voorstel relevant is.

## Bron- en privacyvoorwaarden

1. Controleer identiteit, concrete hoofdactiviteit, dienst, bestaande functionaliteit en exact gepubliceerd zakelijk adres op de **officiële website**; verificatie uit directories/Overture/PDOK is slechts een hint. Verifieer afwijkende maildomeinen via een expliciete koppeling van de officiële website, nooit via een vermoeden. Leid een branche nooit uitsluitend uit een bedrijfsnaam af en leid dieet- of productclaims (zoals veganistisch aanbod) nooit af zonder direct bewijs. Deze zijn historische regressieklassen, geen actueel bevestigd bedrijfsfeit.
2. Noteer bij elke lead privé: feitelijke quote, bronpagina, controledatum, expliciet geverifieerde branche, gepubliceerd adres plus adresbron, bestaande websitefunctionaliteit, onzekerheden en uitsluitings-/historische-dedupe-status. **Privacygevoelige records nooit in publieke repo/CI/logs/PR's**. Ontbrekend bewijs blokkeert de kwaliteitsvrijgave.
3. Zoek **één additionele kans** die niet al als functie aanwezig is. Verkoop geen boekingssysteem aan een bedrijf dat er al één heeft. Een fietsenverkoper met proefritten is niet hetzelfde als een fietsreparateur. Voor restaurants: groepsboekingen ≠ afhalen. Vermijd suggestieve prestatieclaims zonder gecontroleerde onderbouwing.
4. Schrijf één kort, natuurlijk voorstel: toetsbare observatie; concrete aanvulling op bestaande klantreis; één laagdrempelige CTA. Niet “Ik kwam jullie website tegen”, niet “Ik ben Andrew van Webactueel”, geen verzonnen complimenten of resultaten. Maximaal 110 woorden, één commerciële vraag, exacte afmeldzin `Liever geen e-mails meer? Antwoord met 'nee', dan laat ik het hierbij.`, dan `Groet,\nAndrew`.
5. Beoordeel intern met `scripts/lead_quality_gate.py` en gebruik `references/lead-quality-contract.md`. De API accepteert **alleen privé bewijsdata**. De score is redactioneel, nooit omzet, replies of wettelijke verzendtoestemming. Een 10/10 blijft mogelijk, maar alleen na aantoonbaar bewijs, zonder herstelvrije problemen en nooit als conversiegarantie.
6. Verbeter hoogstens twee rondes, herbeoordeel tegen hetzelfde bewijs, stop bij winst <=0.1 of zodra een nieuwe ronde geen aantoonbare verbetering geeft. Eerdere drafts/mailbox nooit automatisch aanpassen. Menselijke eindcontrole blijft verplicht, inclusief Nederlandse regels voor ongevraagde reclame per e-mail.

## Veilig testen en aansluiten

Run de optionele tests op een aparte branch: `python3 -m unittest discover -s tests -p 'test_lead_quality_gate.py' -v`. Verwerk uitsluitend synthetische fixtures; geen privé leaddata in testoutputs. Voor een privé import: `python3 scripts/lead_quality_gate.py --input PRIVATE.jsonl --output PRIVATE-results.jsonl --batch-size 100`. De output en checkpoint zijn privé en bevatten draft-IDs; gebruik nooit publieke artifacts. Inputrecord vereist `draft`, `verification`, `proposal` en de 7 `rubric` velden. Bewaakte input-hash en exacte result/readback verhinderen stil hervatten na gewijzigde brondata.

**Integratiegrens:** dit is een optionele, strengere acceptatielaag. Er is bewust *geen* wijziging aan `draft_queue_readonly.py`, `myhost_draft.py` of live Draft-trigger. Eerst compatibiliteit en autorisatie van privé bewijsrecord, kwaliteitsreadback en regressietests aantonen voordat die productie-gate wordt aangesloten. Een geslaagde CI-run is geen bewijs van websiteverificatie, mailboxopslag of wettelijke toestemming.

## Observaties uit de privé QA450, 2026-10-15

450 / 450 oorspronkelijk geregistreerd; `QA450PerMail`: 206 algemene openingen, 215 diensttermen zonder unieke observatie, 29 specifiek; 27 met broncontrole nodig, 399 herschrijven aanbevolen. `Verbeter450Concepten`: 100 rijen, waarvan 4 onzekere bronnen. `Batch1Topkwaliteit`: 100 rijen; 99 vereisen nog menselijke eindcontrole. Dit zijn **auditclassificaties**, geen onafhankelijke omzet- of conversiemetingen. De gemiddelde originele score was circa 6,77/10. Scores uit verschillende beoordelingsrondes zijn niet rechtstreeks een effectmeting.

## Bronnen en beslisregels

- De actuele vierstappenworkflow en zes templates uit privé Project Leads/Lead Skill zijn basisbeleid; deze interne QA is alleen een kwaliteitsfilter, geen zevende template, CRM of campagne.
- Officiële bedrijfssite/contactpagina: feitelijke autoriteit voor identiteit, aanbod en e-mailadres.
- KVK/CBS SBI 2025: branchecontext, geen zelfstandig bewijs dat een bepaalde functie op de site ontbreekt.
- ACM/Tw art. 11.7: mogelijke juridische blokkade; gepubliceerd adres is geen toestemming.
- Historische dedupe registry en HMAC zijn verplichte suppressiecontrole. Geen opt-out wissen of registry resetten om een batch te laten slagen.
- Gelijke score zonder onafhankelijke feitelijke review is onvoldoende; menselijke redactionele observaties staan los van automatisch controleerbare velden. Geen autonome commerciële claims verzinnen.
