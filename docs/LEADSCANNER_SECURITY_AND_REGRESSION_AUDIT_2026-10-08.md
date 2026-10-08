# Leadscanner — veiligheids-, regressie- en Instantly-audit (8 oktober 2026)

## Besluit

**Technische kwaliteit binnen de geteste scope: 8,2/10.**
**Verzending: NO-GO** totdat de toepasselijke contactgrondslag per lead is aangetoond, de inhoud van de zes e-mailvarianten is beoordeeld en de risico's van publieke review-artifacts zijn geadresseerd.

De audit heeft geen Instantly-campagne geactiveerd, geen lead toegevoegd en geen e-mail verzonden. De bestaande actieve campagne is niet gemuteerd.

## Scope en bewijsniveau

- Repository: `Yolol100/Leadscanner`, branch `main`.
- Bevroren uitgangspunt: `5789c027218e66a918397e55ab7ac2c3c8ac5e22`; **252 bestaande tests** en Instantly static audit 9/9.
- Laatste codefix: `fb509257438113000ac0a30da6747b556aa2677d`.
- Laatste testbewijs voor codefix: [GitHub Actions run 37811472296](https://github.com/Yolol100/Leadscanner/actions/runs/37811472296) — **278 unit-/regressietests, 0 failures, 0 errors, 9/9 statische audit**.
- Live providerbewijs: [read-only Instantly run 37811292179](https://github.com/Yolol100/Leadscanner/actions/runs/37811292179) — 3 commands, 3 groen, 0 fouten, `send_action=false`.
- Live conceptcampagne `59c01c6e-86a6-4417-acab-76f114dca9c5`: Draft (0), 1 sequence, 3 e-mailstappen, 6 varianten, **0 leads**. SHA-256: `4321b2abeb46b2d96f5b75c9d01a08ae4e28414ab27f76d6653459ca8176c3b5`.
- Legacy-campagne `827b1b45-6a7e-45ba-88de-d89db2a47d6a`: Active (1), 1 e-mailstap, ongewijzigde SHA-256 `c43bd0eadc9bcf0340062415c59f8809e236f7990826dc81707610598ed6d2db`.
- De testlaag is **controlled runtime** (mocks/fakes, echte CI) plus **provider read-only**. Er is **geen** echte lead-write, send, UI-/browserproef of juridische compliance-certificering uitgevoerd.
- De actuele Project Leads-manifest-ID uit de controllerregistry gaf bij Google Drive een 404; de live projectbron kon daardoor niet als actuele beleidswaarheid worden geverifieerd. Library-historie is uitsluitend aanvullende context.

## Uitgevoerde scenariofamilies

| ID | Scenariofamilie | Negatieve/positieve voorbeelden | Uitkomst |
|---|---|---|---|
| QA-01 | Prospectherkomst en kwalificatie | Dedupe op identiteit/domein/e-mail/lead-ID, generieke marketingclaims, derdepartijbewijs, ontbrekende officiële e-mail | Bestaande regressies groen |
| QA-02 | Review- en preview-integriteit | Gewijzigde observatie/actie/copy, verlopen of onjuist approvaltoken, immutable snapshot, fact-only vs legacy | Bestaande en nieuwe regressies groen |
| QA-03 | Campagnemergevelden | Onbekende variabele, ontbrekend bewijs, legacy subject/body, losse `}}` of onafgesloten `{{` | Nieuwe regressie groen |
| QA-04 | Instantly staging en readback | Active/Paused/Draft, exacte fingerprint, fout lead-ID, onjuist providerresultaat, `"false"` i.p.v. boolean `false` | Nieuwe regressies groen |
| QA-05 | Activatie/autorisatie | Ontbrekende/stale sequentiehash, gewijzigde leadset, ongeverifieerde contactgrondslag, boolean campagnestatus, verkeerde campagne-ID | Nieuwe regressies groen |
| QA-06 | Mutatie tijdens preflight | Campagne-, leadpayload-, providerstatus- of registrywijziging vóór activering | Nieuwe regressies groen |
| QA-07 | Suppressie en verzending | Unsubscribe, bounce, skip, negatieve intereststatus, ontbrekende/ambigue canonical registry-rij | Nieuwe regressies groen |
| QA-08 | Campagne-PATCH en veiligheidsinstellingen | API accepteert PATCH maar negeert sequence, afzender, stop-on-reply, unsubscribe-header of daglimiet | Nieuwe regressies groen |
| QA-09 | Providertransport en commandogates | HTTP 429/5xx, geen write-retry, exact confirmation, rerun-blokkade, redactie van secrets, async jobs | Bestaande regressies groen |
| QA-10 | Live Instantly (alleen lezen) | Draft-activatiegereedheid, Draft-sequentie, legacy-sequentie | **3/3 groen, 0 verzendacties** |

**Netto testuitbreiding:** 26 nieuwe testmethoden (252 → 278). Subtests en varianten zijn niet kunstmatig als afzonderlijke testmethoden geteld.

## Gerepareerde bewezen gaten

1. **Activation drift / toestemming:** aparte activatiegoedkeuring is nu gebonden aan de actuele campagnehash **en** de exacte leadset-hash. Wijzigingen tussen review en activatie blokkeren de actie.
2. **Contactgrondslag:** voor elke Leadscanner-lead is `leadscanner_contact_basis` (`consent_verified` of `existing_customer_related_verified`) plus een onafhankelijke, opaque bewijsreferentie vereist. Een publiek zakelijk e-mailadres voldoet niet.
3. **Registry/suppressie:** activatie vereist per lead een unieke canonieke registry-identiteit met dezelfde lead-ID en status `instantly_staged`, gecontroleerd vóór en direct voorafgaand aan activatie. Unsubscribed/replied/bounced of ontbrekende rijen blokkeren.
4. **Providerstatus:** bounced/unsubscribed/skipped en negatieve intereststatus blokkeren activatie, ook bij een technisch geverifieerd e-mailadres.
5. **Type- en identity-hardening:** boolean `false` is geen geldige Draft-status; campagne-ID en provider-lead-ID moeten exact terugkomen.
6. **Template-parser:** ongepaarde opening- én sluitmarkeringen van Instantly-mergevelden worden afgewezen.
7. **Registry-closure:** alleen echte boolean `true` bij exact readback geldt als bewijs, geen truthy strings.
8. **PATCH-readback:** sequences/varianten, afzender, reply-stops, tracking, uitschrijfheader, risicocontacten en daglimieten moeten werkelijk door Instantly zijn opgeslagen. HTTP-succes alleen is onvoldoende.

De fixes zijn klein en behouden de bestaande preview-, legacy-mail- en dedupepaden. De `instantly_stage`-stap verstuurt nog steeds niets.

## Openstaande risico's (niet automatisch gewijzigd)

| Ernst | Punt | Waarom nog open / noodzakelijke actie |
|---|---|---|
| **Hoog / verzendblocker** | Juridische toestemming/contactbasis niet bewezen | Controleer per ontvanger de oorspronkelijke opt-in of toepasselijke bestaande-klantuitzondering, inclusief reikwijdte, bewijsreferentie en afmeldmogelijkheid. De nieuwe activatiepoort blokkeert ontbrekend bewijs, maar kan de echtheid van een handmatig ingevulde referentie niet zelfstandig vaststellen |
| **Hoog / privacy** | Openbare GitHub-repository met review-artifacts | De preview-workflow bewaart reviewbestanden met zakelijke contact- en observatiegegevens maximaal 7 dagen. Beoordeel besloten reviewopslag, encryptie of kortere bewaartermijn. Geen stille repositoryprivatisering of verlies van reviewcapaciteit toegepast |
| **Hoog / buiten codepoort** | Instantly-UI en bestaande actieve legacy-campagne | De repositorypoort beheerst geen handmatige activatie/verzending in de Instantly-UI. De bestaande campagne is Active; er is geen opdracht uitgevoerd om deze te pauzeren. Verifieer bestaande verzend-/contactgrondslag separaat |
| **Middel** | Geen live write/send-E2E | Alleen provider read-only smoke is uitgevoerd; staging, daadwerkelijke verzending en afmeldflow zijn niet in productie beproefd, bewust om geen commerciële communicatie te veroorzaken |
| **Middel** | Project Leads-manifest niet bereikbaar | Herstel of verifieer het actuele Google Drive-manifest en de bronstatus vóór formele project-/compliance-closure |
| **Middel** | Copy/UX-review | Beoordeel alle zes onderwerp/body-varianten en rendering met echte goedgekeurde eerste-partijdata; technische variabelencontrole is geen inhoudelijke copykeuring |

## Scoremethodiek (beperkt tot de onderzochte technische keten)

| Onderdeel | Gewicht | Score |
|---|---:|---:|
| Regressiedekking en reproduceerbaarheid | 25% | 9,2 |
| Veiligheids- en goedkeuringspoorten | 25% | 8,8 |
| Dedupe, registry en readback-integriteit | 20% | 9,0 |
| Instantly-integratiebewijs | 15% | 8,0 |
| Compliance- en privacygereedheid | 15% | 4,5 |
| **Gewogen eindcijfer** | **100%** | **8,2/10** |

De 9/9 statische audit telt **geen** 9/9 voor juridische naleving of productiegeschiktheid. **QA-besluit: Conditional GO voor verdere review en gecontroleerde tests; NO-GO voor commerciële verzending.**

## Officiële bronnen

- ACM spamregels: https://www.acm.nl/nl/verkoop-aan-consumenten/reclame-en-verleiden/spam-voorkomen-uw-reclame
- Instantly API v2 Lead-schema: https://developer.instantly.ai/api-reference/schemas/lead
- Instantly API v2: https://help.instantly.ai/en/articles/10432807-api-v2

Geen automatische verzending, activatie of destructieve campagnehandeling maakt deel uit van deze audit.
