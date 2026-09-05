# Leadscanner repository instructions

## Scope

- Dit is de centrale GitHub-runtime voor `leads`.
- Gebruik `toolkit-contract.json` als machineleesbaar capabilitycontract en `LEADS-INTEGRATION.md` als menselijke uitvoeringsgrens. Dupliceer die details niet opnieuw in andere docs.
- De twaalf capabilities zijn: `prospect_discovery`, `contact_enrichment`, `website_evidence_scan`, `sender_readiness`, `inbox_placement`, `mailbox_draft`, `outreach_delivery`, `dashboard`, `prospect_intelligence`, `prospect_signal_discovery`, `prospect_qualification` en `zero_touch_prepare`.
- `leads` bezit de beleidscontracten voor realness, Customer Potential, compliancebasis/status, LeadPromo-copy en interpretatie van readback.
- De repository mag die beleidscontracten deterministisch uitvoeren voor begrensde qualification en prepare, maar mag nooit compliance automatisch goedkeuren of send permission creëren.
- `webactueel-workflow` bezit cross-skill routing, bronselectie en totale closure.
- `Yolol100/Orchestrator` is geen technische dependency.

## Capabilitygrenzen

- `prospect_discovery`: alleen goedgekeurde `ProspectSources`; company/domain-kandidaten; geen contacts, score, copy, compliance of mailcredentials.
- `prospect_signal_discovery`: bounded official-site hiring/WordPress/WooCommerce evidence; adviserend, geen score-/permissionmutatie.
- `prospect_qualification`: alleen `discovered/hold`; bounded official homepage; Customer Potential volgens Leads; één primaire opportunityseverity; A vereist evidence-bound fact+idea; schrijft `ProspectQualifications`; geen compliance/send permission.
- `contact_enrichment`: alleen `qualified`; begrensde officiële-site-evidence; nooit adressen raden/construeren en nooit send permission creëren.
- `prospect_intelligence`: afgeleide evidence/freshness/source/lookalike-laag; adviserend en geen compliance/send permission.
- `zero_touch_prepare`: orchestreert discovery -> signals -> qualification -> contact -> intelligence -> prepare; alleen A + ready contact; queue blijft `status=prepared`, `compliance_status=manual_review`, lege `compliance_basis`; geen mailboxsecrets of SMTP.
- `website_evidence_scan`: optioneel read-only, publieke officiële sites, GET/HEAD-only; evidence verandert nooit zelfstandig compliance/send permission.
- `sender_readiness`: technische senderdiagnostiek; exact-IP checks wanneer expliciet geconfigureerd; bewezen mijn.host shared relay mag `provider_managed` zijn zonder per-IP reputatie/placement te claimen.
- `inbox_placement`: handmatig, seed-only, standaard `validate`, maximaal vijf geconfigureerde seed-inboxen; nooit `OutreachQueue`.
- `mailbox_draft`: expliciete self-only test; uitsluitend mijn.host IMAP `APPEND` + dezelfde-map-readback, nooit SMTP en nooit Google Sheet-toegang.
- `outreach_delivery`: alleen afzonderlijk goedgekeurde state; manual default `validate`; live vereist expliciete live-keuze plus alle readiness/compliance/suppression/transportgates.
- `dashboard`: read-only aggregatie; mag geen Lead- of transportstate muteren.

## Secretgrenzen

- Commit, print, log of artifact nooit secretwaarden.
- Discovery/signal/qualification/contact/intelligence/prepare krijgen geen mailboxsecrets.
- `zero_touch_prepare` krijgt alleen `GOOGLE_SERVICE_ACCOUNT_JSON` en gewone vars.
- Sheet-only preflights/reporting krijgen geen mailboxsecrets.
- `mailbox_draft` krijgt alleen de mailboxconfiguratie/credential die IMAP-auth vereist en nooit `GOOGLE_SERVICE_ACCOUNT_JSON`.
- Productie-SMTP/IMAP-secrets zijn alleen beschikbaar in expliciete live/mailboxstappen die ze nodig hebben.
- CI voert nooit live send uit.
- `workflow_run`-sender-readiness mag secrets alleen gebruiken na een succesvolle `push`-run van Leads Runtime CI op `main`; nooit na een PR-run.

## Voor wijzigingen

- Lees voor runtimewerk: `LEADS-INTEGRATION.md`, `toolkit-contract.json`, `tool-registry.json`, de relevante workflow en de directe scriptclosure.
- Houd secrets en runtime-output buiten `main`; run-evidence blijft in Actions artifacts/Sheets.
- Tijdelijke connector-triggerstate zoals `ops/leads-autopilot-request.txt` moet na bewezen run worden verwijderd.
- Voeg geen provider, verifier, warmup-netwerk of extra controller toe zonder aantoonbaar capabilitygat en tests.
- Verwijder alleen code/docs wanneer callsites, contracten en tests bewijzen dat ze werkelijk overbodig zijn.
- Qualificatie-automatisering mag geen generieke hiaten optellen tot een kunstmatig sterke score en mag een site niet als webshop behandelen op alleen het woord `product`.

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

Behoud daarnaast de contractchecks voor capabilitydekking, zero-touch secret-isolatie, qualification audit trail, prepare-only state, fail-closed live-volgorde en `mailbox_draft` zonder SMTP/Sheet.

## Evidencegrenzen

- Discovery maakt kandidaten, geen goedgekeurde leads.
- `ProspectQualifications` is een reproduceerbaar kwalificatiebesluit, geen compliancebewijs.
- Prepared mailcopy is reviewstate, geen sendbewijs.
- Scanneroutput is technisch/browserbewijs; SMTP-acceptatie is geen inbox-placementbewijs.
- `provider_managed` is geen bewijs van één vast outbound IP, per-IP blockliststatus of globale inboxplaatsing.
- Creatorvideo's en comments zijn adviserend bewijs; actuele wet/providerregels en echte Webactueel-uitkomsten wegen zwaarder.
- Groene repositorytests bewijzen code/contracts. Live mailbox/Sheet readiness vereist aparte geconfigureerde preflight/readback.
