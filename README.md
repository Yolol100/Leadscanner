# Leadscanner

De enige flow is:

**candidate discovery -> officiële website/webshop -> evidence -> één primaire aanbodfamilie -> contactbasis -> korte mail -> controle -> mijn.host-concept -> stop.**

ChatGPT/Leads doet de inhoudelijke kwalificatie en de Nederlandse/EER-contactpoort. Deze repo doet de technische DraftQueue-validatie en het mijn.host-concept. De keyless discovery-capability gebruikt Overture Maps Places plus PDOK voor Nederlandse regiolocatie; discovery-hints zijn nooit prospectbewijs en Leads moet bedrijf + domein rechtstreeks op de officiële site verifiëren. Er is geen SMTP-sendroute.

## Canonieke uitvoerprompt

Gebruik deze prompt voor een leadrun:

> Zoek [AANTAL] nieuwe bedrijven via de door Leads geautoriseerde discovery-capability binnen [BRANCHE/REGIO]. Gebruik discovery alleen om kandidaten te vinden. Open voor iedere kandidaat de echte officiële website of webshop en ga alleen verder als bedrijf en website aantoonbaar bij elkaar horen. Beoordeel exact vier commerciële aanbodfamilies (`ai_agents`, `social_media`, `search_visibility`, `website_webshop`) en kies precies één primaire familie op basis van concrete actuele evidence. Bewaar de observatie en bron-URL. Zoek het beste publieke zakelijke e-mailadres, raad nooit een adres en bewaar de exacte officiële bronpagina. Ga vóór DraftQueue alleen door wanneer Leads een aantoonbare contactbasis heeft vastgesteld; publiek zichtbaar e-mailadres alleen is onvoldoende. Schrijf één korte natuurlijke mail met één observatie, één primair resultaat, hoogstens één prijsloze value-first actie, één kleine permission-CTA, Andrew Baeten + andrewbaeten.nl en een simpele afmelding. Controleer alles. Zet alleen volledig gecontroleerde leads in DraftQueue. Maak daarna uitsluitend mijn.host IMAP-concepten. Lees ieder concept terug en vergelijk ontvanger, onderwerp en body exact. Verzend niets.

## Actieve DraftQueue

Alleen deze velden zijn actief:

`lead_id`, `company`, `website`, `offer`, `observation`, `observation_source_url`, `email`, `email_source_url`, `subject`, `body`, `contact_basis_status`, `contact_basis_type`, `contact_basis_evidence_ref`, `outreach_status`, `draft_queue_eligible`

Toegestane `offer`-waarden:

- `ai_agents`
- `social_media`
- `search_visibility`
- `website_webshop`

Legacy labels zoals `conversion_contact`, `wordpress_elementor` en `seo` worden afgewezen. WordPress/Elementor/contactflow/technische SEO zijn onderliggende oplossingsvormen en geen extra commerciële hoofdaanbiedingen.

De twee source-URL's moeten op de officiële website/webshop staan. De repo valideert daarnaast de finale contactbasisvelden fail-closed: `contact_basis_status=pass`, een toegestane `contact_basis_type`, `outreach_status=ready_for_draftqueue` en `draft_queue_eligible=true`.

## Mijn.host command

De normale route gebruikt `workflow_dispatch` op **Create selected mijn.host concepts** met:

- `lead_ids`: komma- of newlinegescheiden DraftQueue-ID's;
- `expected_count`: exact verwacht aantal.

Wanneer de verbonden ChatGPT/GitHub-surface geen `workflow_dispatch`-actie aanbiedt, mag dezelfde gecontroleerde runtime ook via een tijdelijke branch worden gestart:

`runtime/myhost-draft/<lead_id>`

Daarvoor gelden harde grenzen:

- precies één bestaande DraftQueue-`lead_id` per runtimebranch;
- alleen letters, cijfers, punt, underscore en koppelteken; maximaal 80 tekens;
- de eerste `create`-listener heeft geen mailboxsecrets;
- de IMAP-runtime start pas daarna via `workflow_run` en checkt expliciet de default branch uit;
- dezelfde `validate_row`, DraftQueue-readback en exacte IMAP-readback blijven gelden;
- de tijdelijke runtimebranch wordt na afloop door een apart cleanup-job verwijderd;
- er is nog steeds geen GitHub-issue/commentroute en geen SMTP-sendroute.

`DraftQueue.body` blijft de gevalideerde kerntekst. Vlak vóór IMAP voegt de runtime uitsluitend het privé geconfigureerde zakelijke postadres toe als compliance-footer. Ontbreekt dat adres, dan blokkeert de run. Daarna worden `To`, `Subject` en de volledige uiteindelijke conceptbody exact uit mijn.host teruggelezen. Het privé postadres komt niet in de publieke repo of logs.


## Keyless discovery

`Overture keyless discovery` is de repository-capability voor discovery zonder API-key, account of secret.

Route:

`PDOK regio -> Overture Places bbox -> branchefilter -> website-hint -> optionele directe HTTP-readback -> Leads identity verification`

Grenzen:

- PDOK Locatieserver is open/gratis en wordt alleen gebruikt om een Nederlandse plaats/gemeente naar een centrumcoördinaat te vertalen;
- de officiële `overturemaps==1.0.2` client leest de meest recente Overture Places-release rechtstreeks uit publieke cloudopslag;
- Overture `emails`, `phones` en `socials` worden nooit in het discovery-handoffrecord opgenomen;
- Overture naam/categorie/website zijn alleen candidate hints; ze autoriseren geen prospectclaim;
- `identity_status` blijft `needs_leads_verification` totdat Leads de officiële website rechtstreeks heeft gecontroleerd;
- geen contactbasis, offerkeuze, DraftQueue-write of mailactie in discovery;
- artifacts worden 1 dag bewaard en prospecttargets worden niet naar de default branch geschreven;
- voor grotere aantallen gebruikt de controller meerdere compacte branche/regioqueries in plaats van één onbegrensde download.


Wanneer de verbonden ChatGPT/GitHub-surface geen `workflow_dispatch` aanbiedt, mag keyless discovery via een tijdelijke branch worden gestart:

`runtime/overture-discovery/<request_id>`

Plaats alleen `requests/overture-discovery.json` op die branch. De request is begrensd tot één regio of bbox, maximaal 12 keywords en maximaal 100 candidate hints. De workflow schrijft alleen een 1-dags artifact en verwijdert de tijdelijke branch na completion. Dit transport verandert niets aan de Leads-ownergrenzen.
