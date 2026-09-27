# Leadscanner

Eén flow:

`vinden/filteren -> verifiëren -> korte Groeiabonnement-mail -> mijn.host review_draft + exacte readback`

- Discovery: PDOK + Overture + Google Maps, dedupe, concurrenten eruit.
- Verificatie: officiële site, NL/EN en zakelijk e-mailadres. E-mailvolgorde: site -> Overture -> gerichte Maps-fallback.
- Aanbod: één Groeiabonnement van €250–€500 p/m met zes onderdelen.
- Draft: alleen IMAP naar mijn.host. Publieke e-mail blijft `review_required`.
- Veiligheid: nooit e-mail raden, nooit automatisch verzenden, exact gevraagde drafts teruglezen.

Start via `workflow_dispatch` of een owner-only `[growth-draft]` issue met JSON-body.
