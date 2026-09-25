# Leadscanner

De standaardflow is bewust simpel:

**bedrijven verzamelen -> concurrenten/bureaus uitsluiten -> officiële e-mail controleren -> NL/EN bepalen -> kort concept maken -> goedgekeurde concepten in mijn.host opslaan**

## Groeiabonnement

Er is één product: **Groeiabonnement**, normaal **€250-€500 per maand afhankelijk van scope**.

De zes onderdelen:

1. website/webshop verbeteren;
2. zoekbaarheid verbeteren;
3. social content verzorgen;
4. geschikte repetitieve werkzaamheden tot circa 30% automatiseren waar aantoonbaar haalbaar is;
5. hosting overnemen/beheren wanneer passend;
6. Andrew als vast contactpersoon voor aanpassingen en ondersteuning.

## Enige standaardworkflow

Open **Actions -> Leads Batch - Groeiabonnement -> Run workflow**.

De workflow doet:

`PDOK + Overture + Google Maps -> dedupe -> maximaal 100 websites/contacten controleren -> bureaus uitsluiten -> publiek zakelijk e-mailadres vinden -> taal NL/EN bepalen -> Groeiabonnement-concept maken -> draft_ready naar mijn.host Concepten`

Discovery kan tot 5.000 kandidaatbedrijven verzamelen. De officiële website/e-mail/conceptcontrole blijft per gecontroleerde run maximaal 100 kandidaten, zodat de output reviewbaar blijft.

## Wat wordt uitgesloten

De Leadscanner benadert geen bedrijven waarvan de kernactiviteit materieel overlapt met Webactueel. Minimaal uitgesloten:

- marketing-, reclame- en communicatiebureaus;
- webbureaus, webdesign- en webdevelopmentbureaus;
- SEO-bureaus;
- social-media- en contentmarketingbureaus;
- AI/automation/no-code agencies;
- WordPress/WooCommerce/Elementor-bureaus;
- digitale bureaus;
- hostingproviders en hostingresellers.

Naam/categorie wordt vroeg gebruikt om werk te besparen. De officiële website is de finale controle. Bij twijfel wordt een bedrijf overgeslagen.

## E-mail en taal

De Leadscanner gebruikt alleen een exact publiek zakelijk e-mailadres dat rechtstreeks op de officiële bedrijfswebsite staat. Er worden geen adressen geraden of geconstrueerd.

De website bepaalt de mailtaal:

- Nederlandstalige site -> Nederlandse mail;
- Engelstalige site -> Engelse mail;
- HTML `lang` heeft voorrang;
- zichtbare paginatekst is fallback;
- onduidelijk + Nederlandse markt -> Nederlands, anders Engels.

## Conceptmail

De mail is kort, ongeveer 55-95 woorden, en legt één Groeiabonnement uit voor **€250-€500 per maand afhankelijk van scope**.

De zes onderdelen staan compact in de mail. De tekst bevat één CTA, Andrew Baeten + `andrewbaeten.nl` en een eenvoudige afmeldzin.

De repo maakt een `concept_preview` zodra een bruikbaar bedrijf/contact is gevonden. Een daadwerkelijk geadresseerde `body` blijft geblokkeerd totdat de actuele contactbasis op `pass` staat.

## mijn.host Concepten

`scripts/myhost_draft.py` schrijft uitsluitend rijen met `status=draft_ready` én `contact_basis_status=pass` via IMAP naar de Concepten/Drafts-map van mijn.host en leest daarna exact ontvanger, onderwerp en body terug.

Standaardinstellingen:

- IMAP-host: `mail.andrewbaeten.nl`;
- IMAP-poort: `993` met SSL;
- account: `info@andrewbaeten.nl`;
- wachtwoord uitsluitend via GitHub secret `OUTREACH_MAIL_PASSWORD`;
- geen SMTP-code en geen automatische verzending.

Als een run geen goedgekeurde rijen bevat, wordt geen mailboxverbinding gemaakt en worden nul drafts aangemaakt.

## Na interesse

Pas na een positieve reactie wordt specialistisch verdiept via Design, SEO, social, WordPress/Elementor/programmeren of hosting.

## Veiligheidsgrenzen

- een publiek e-mailadres is geen toestemming;
- concurrenten krijgen geen concept;
- geen automatische verzending;
- geen verzonnen prospectproblemen, resultaten of garanties;
- prospecttargets en mailboxbewijs horen niet in de default branch.
