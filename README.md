# Leadscanner

De enige flow is:

**Google Maps -> officiële website/webshop -> evidence -> één primaire aanbodfamilie -> contactbasis -> korte mail -> controle -> mijn.host-concept -> stop.**

ChatGPT/Leads doet de inhoudelijke kwalificatie en de Nederlandse/EER-contactpoort. Deze repo doet alleen de technische DraftQueue-validatie en het mijn.host-concept. Er is geen SMTP-sendroute.

## Canonieke uitvoerprompt

Gebruik deze prompt voor een leadrun:

> Zoek [AANTAL] nieuwe bedrijven via Google Maps binnen [BRANCHE/REGIO]. Gebruik Maps alleen om kandidaten te vinden. Open voor iedere kandidaat de echte officiële website of webshop en ga alleen verder als bedrijf en website aantoonbaar bij elkaar horen. Beoordeel exact vier commerciële aanbodfamilies (`ai_agents`, `social_media`, `search_visibility`, `website_webshop`) en kies precies één primaire familie op basis van concrete actuele evidence. Bewaar de observatie en bron-URL. Zoek het beste publieke zakelijke e-mailadres, raad nooit een adres en bewaar de exacte officiële bronpagina. Ga vóór DraftQueue alleen door wanneer Leads een aantoonbare contactbasis heeft vastgesteld; publiek zichtbaar e-mailadres alleen is onvoldoende. Schrijf één korte natuurlijke mail met één observatie, één primair resultaat, hoogstens één prijsloze value-first actie, één kleine permission-CTA, Andrew Baeten + andrewbaeten.nl en een simpele afmelding. Controleer alles. Zet alleen volledig gecontroleerde leads in DraftQueue. Maak daarna uitsluitend mijn.host IMAP-concepten. Lees ieder concept terug en vergelijk ontvanger, onderwerp en body exact. Verzend niets.

## Actieve DraftQueue

Alleen deze velden zijn actief:

`lead_id`, `company`, `website`, `offer`, `observation`, `observation_source_url`, `email`, `email_source_url`, `subject`, `body`

Toegestane `offer`-waarden:

- `ai_agents`
- `social_media`
- `search_visibility`
- `website_webshop`

Legacy labels zoals `conversion_contact`, `wordpress_elementor` en `seo` worden afgewezen. WordPress/Elementor/contactflow/technische SEO zijn onderliggende oplossingsvormen en geen extra commerciële hoofdaanbiedingen.

De twee source-URL's moeten op de officiële website/webshop staan. De juridische/contactbasis wordt vóór DraftQueue door Leads gecontroleerd en behoort niet tot deze technische repo-validatie.

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

De conceptbody wordt niet intern aangepast: `DraftQueue.body` is de definitieve body en wordt exact via IMAP teruggelezen.
