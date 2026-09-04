# Leadscanner repository instructions

## Scope

- Dit is de centrale GitHub-runtime voor `leads`.
- Gebruik `toolkit-contract.json` als machineleesbaar capabilitycontract en `LEADS-INTEGRATION.md` als menselijke uitvoeringsgrens. Dupliceer die details niet opnieuw in andere docs.
- De acht capabilities zijn: `prospect_discovery`, `contact_enrichment`, `website_evidence_scan`, `sender_readiness`, `inbox_placement`, `mailbox_draft`, `outreach_delivery` en `dashboard`.
- `leads` bezit realness, Customer Potential/kwalificatie, contactkeuze, compliancebasis/status, mailcopy en interpretatie van readback.
- `webactueel-workflow` bezit cross-skill routing, bronselectie en totale closure.
- `Yolol100/Orchestrator` is geen technische dependency.

## Capabilitygrenzen

- `prospect_discovery`: alleen goedgekeurde `ProspectSources`; company/domain-kandidaten; geen contacts, score, copy, compliance of mailcredentials.
- `contact_enrichment`: alleen `qualified` kandidaten; begrensde officiële-site-evidence; nooit adressen raden/construeren en nooit send permission creëren.
- `website_evidence_scan`: optioneel read-only, publieke officiële sites, GET/HEAD-only; evidence verandert nooit zelfstandig leadfit/compliance/send permission.
- `sender_readiness`: technische senderdiagnostiek; geen commerciële toestemming en geen globale placementclaim.
- `inbox_placement`: handmatig, seed-only, standaard `validate`, maximaal vijf geconfigureerde seed-inboxen; nooit `OutreachQueue`.
- `mailbox_draft`: expliciete self-only test; uitsluitend mijn.host IMAP `APPEND` + dezelfde-map-readback, nooit SMTP en nooit Google Sheet-toegang.
- `outreach_delivery`: alleen vooraf beoordeelde Leads-state; manual default `validate`; live vereist expliciete live-keuze plus alle readiness/compliance/suppression/transportgates.
- `dashboard`: read-only aggregatie; mag geen Lead- of transportstate muteren.

## Secretgrenzen

- Commit, print, log of artifact nooit secretwaarden.
- Discovery/contact-only routes krijgen geen mailboxsecrets.
- Sheet-only preflights/reporting krijgen geen mailboxsecrets.
- `mailbox_draft` krijgt alleen de mailboxconfiguratie/credential die IMAP-auth vereist en nooit `GOOGLE_SERVICE_ACCOUNT_JSON`.
- Productie-SMTP/IMAP-secrets zijn alleen beschikbaar in expliciete stappen die ze nodig hebben.
- CI voert nooit live send uit.

## Voor wijzigingen

- Lees voor runtimewerk: `LEADS-INTEGRATION.md`, `toolkit-contract.json`, `tool-registry.json`, de relevante workflow en de directe scriptclosure.
- Houd concrete requeststate buiten `main`; run-evidence blijft in Actions artifacts/Sheets.
- Voeg geen provider, verifier, warmup-netwerk of extra controller toe zonder aantoonbaar capabilitygat en tests.
- Verwijder alleen code/docs wanneer callsites, contracten en tests bewijzen dat ze werkelijk overbodig zijn.

## Validatie

Scanner/runtime:

```bash
npm ci
npm test
npm run check:crawler
npm run check:tools
```

Leads Python:

```bash
python3 -m pip install -r requirements-outreach.txt
python3 -m compileall -q scripts
PYTHONPATH=scripts python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Behoud daarnaast de contractchecks voor capabilitydekking, secret-isolatie, fail-closed live-volgorde en `mailbox_draft` zonder SMTP/Sheet.

## Evidencegrenzen

- Discovery maakt kandidaten, geen goedgekeurde leads.
- Scanneroutput is technisch/browserbewijs; SMTP-acceptatie is geen inbox-placementbewijs.
- Creatorvideo's en comments zijn adviserend bewijs; actuele wet/providerregels en echte Webactueel-uitkomsten wegen zwaarder.
- Groene repositorytests bewijzen alleen code/contracts. Live mailbox/Sheet readiness vereist aparte geconfigureerde preflight/readback.
