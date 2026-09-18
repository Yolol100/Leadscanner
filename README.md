# Leadscanner

De enige flow is:

**Google Maps -> officiële website/webshop -> passend aanbod -> beste publieke zakelijke e-mail -> korte mail -> controle -> mijn.host-concept -> stop.**

ChatGPT/Leads doet de inhoudelijke stappen. Deze repo doet alleen de technische eindcontrole en het mijn.host-concept. Er is geen SMTP-sendroute.

## Canonieke uitvoerprompt

Gebruik deze prompt voor een leadrun:

> Zoek [AANTAL] nieuwe bedrijven via Google Maps binnen [BRANCHE/REGIO]. Gebruik Maps alleen om kandidaten te vinden. Open voor iedere kandidaat de echte officiële website of webshop en ga alleen verder als bedrijf en website aantoonbaar bij elkaar horen. Kies precies één passend aanbod op basis van één concrete, actuele observatie op die website. Bewaar de observatie én de exacte bron-URL. Zoek daarna het beste publieke zakelijke e-mailadres in deze volgorde: bewezen beslisser, passende afdeling, algemeen bedrijfsadres. Raad of bouw nooit een e-mailadres. Bewaar de exacte pagina waarop het e-mailadres publiek staat. Schrijf één korte natuurlijke mail met één observatie, één aanbod, één kleine permission-CTA, Andrew Baeten + andrewbaeten.nl en een simpele afmelding. Controleer alle feiten, bron-URL's, e-mail, aanbod, taal en placeholders. Zet alleen volledig gecontroleerde leads in DraftQueue. Maak daarna uitsluitend mijn.host IMAP-concepten. Lees ieder concept terug en vergelijk ontvanger, onderwerp en body exact. Verzend niets. Stop na groene readback zodat Andrew zelf kan controleren en verzenden.

## Actieve DraftQueue

Alleen deze velden zijn actief:

`lead_id`, `company`, `website`, `offer`, `observation`, `observation_source_url`, `email`, `email_source_url`, `subject`, `body`

Toegestane `offer`-waarden:

- `website_webshop`
- `wordpress_elementor`
- `seo`
- `conversion_contact`

De twee source-URL's moeten op de officiële website/webshop staan. Zo kan de laatste controle bewijzen waar observatie en e-mail vandaan kwamen.

## Mijn.host command

De normale route gebruikt `workflow_dispatch` op **Create selected mijn.host concepts** met:

- `lead_ids`: komma- of newlinegescheiden DraftQueue-ID's;
- `expected_count`: exact verwacht aantal.

Daarmee is geen GitHub-issue, comment of close-write nodig. De workflow heeft geen issue-trigger of issue-schrijfpermissie.

De conceptbody wordt niet meer intern aangepast: `DraftQueue.body` is de definitieve body en wordt exact via IMAP teruggelezen. Er is geen SMTP-sendroute.
