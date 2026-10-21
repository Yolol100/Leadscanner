# Leads: evidence-first mail and video route (phase 3, opt-in)

This is **new generic capability code only**. It is not yet wired into the
owner-only GitHub issue command or production DraftQueue. Existing four-step
Leadscanner, historical/HMAC suppressions, six active templates, Mijn.Host
IMAP Draft readback, old drafts and no-send rule remain unchanged.

## Fast decision path

1. The existing owner-authorized discovery must verify official website,
   allowed local trade, publicly listed business email, complete historical
   suppression and duplicate state, and exactly the request count (or partial).
2. For each newly verified candidate, reuse no more than **three** official
   public pages: homepage, relevant service/product page, contact page.
   An observed *mention* never proves a function works or is absent.
3. With a **private, evidence-backed** opportunity and live dated source,
   select at most five video candidates. No audit or numerical score for the
   others. An unmet criterion skips the candidate.
4. For selected video leads only: make dated safe observations of key flows,
   current-vs-proposed UX/CRO/SEO improvements; retrieve real Ahrefs Netherlands
   values, local competitors and honest on-screen scripts. No conversions,
   positions, or sales are guaranteed. Never show private pages on screen.
5. Other eligible leads get a subject that is personal, short and neutral,
   followed by the exact `Goedendag,` / `Ik zag dat ...` / `Zou het handig zijn
   als ...?` / opt-out / `Groet, Andrew` layout. Only human-approved facts,
   relevance and features not already known to be available.
6. Store only via existing authorized private DraftQueue -> Mijn.Host `\\Draft`
   path with exact same-folder UID/readback; final human legal and content
   review is required; **never automatically send**.

## Implementation limitations

`scripts/lead_video_planner.py` is a **pure Python, no-network helper** with
`route_verified_leads`, `render_short_email`, and `prepare_video_storyboard`.
It expects proof/authorization flags and dated evidence supplied by the
controller. It **does not** independently check the live suppression registry,
scan a site, call Ahrefs, save a Draft, verify legal contact rights, or record
an MP4. Do not expose the private inputs in public CI or logs.

No GitHub Actions event, CLI, cron or email automation is added by this patch.
The production switch requires reconciliation of the active Leads Google
Drive source, its hash manifest, installed Leads Skill, six-template policy,
private source authorization, and an independent end-to-end test, plus owner
approval. Do not bulk-rewrite existing drafts without a durable individual
MIME backup, UID/SHA preflight, explicit authority and readback.

## Tests

`PYTHONPATH=scripts python3 -m unittest discover -s tests -p 'test_lead_video_planner.py' -v`

The tests use only invented `.example` domains; no network, Sheets or mail.
