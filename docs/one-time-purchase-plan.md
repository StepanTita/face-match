# One-time purchase: plan

Goal: sell `facematch` as a single $19 one-time purchase. Buyer pays once via
a Stripe Payment Link, Stripe automatically emails them a download link for
the installers, no backend/webhook/email service needed. Lost-email or
"I need it again" cases are handled manually via a support email address,
not a self-service portal.

## GitHub stays exactly as it is

The landing page has no link to GitHub anywhere on it today (checked:
`Nav.tsx`, `Footer.tsx`, etc. — none). So the free `install.sh` /
public-release path on GitHub and the paid path on the landing page serve
two different audiences that barely overlap: people who already know to
look at the repo could always build/install for free (that's fine, it's
MIT), while people who find `facematch` through Google/an AI answer and
land on the marketing page have no free path presented to them — they pay.
No changes needed to `install.sh`, the README, or the release workflow's
public binaries.

## Steps

1. **Packaging: one combined archive.**
   The zip attached to Stripe doesn't need to come from the public release
   pipeline at all — build it as a one-off (or a small separate script) that
   bundles the macOS arm64 + Linux x86_64 binaries together into a single
   `facematch-installers.zip`, plus a plain `README.txt` inside saying which
   file to run on which OS (no install script, no platform detection — just
   two binaries and instructions). This zip is the one file attached to the
   Stripe product — buyers get both platforms from one link regardless of
   which OS they're on.

2. **Stripe setup (dashboard, no code):**
   - Create a Product: "facematch", $19, one-time.
   - Attach `facematch-installers.zip` as the product's digital-download
     file (Stripe's built-in "sell digital downloads" feature).
   - Create a Payment Link for it. Stripe hosts checkout, collects the
     buyer's email, and automatically emails them the download link as
     part of the receipt after successful payment — no webhook or email
     service (e.g. Resend) required.
   - Each new release: re-upload the updated zip to the same Stripe
     product so new purchases get the latest build. (Manual step, by
     design — no auto-update pipeline for now.)

3. **Site changes (`site/`):**
   - `components/Pricing.tsx`: keep the `$19 one-time` copy, replace the
     `WaitlistForm` with a plain link/button pointing straight at the
     Stripe Payment Link URL.
   - Delete `components/WaitlistForm.tsx` (no client-side form or state
     needed — Stripe Checkout collects the email itself).
   - Add a line near the price: "You'll get a download link by email right
     after purchase."
   - `components/Footer.tsx`: replace the placeholder `Contact` link with a
     real support email (`mailto:`), for lost-email / re-download requests.

4. **Out of scope for this plan** (separate pass, per earlier discussion):
   SEO work (metadata, structured data, sitemap, content for Google + AI
   chat discoverability) — tracked separately, not part of this purchase
   flow change.

## Open items to confirm

- [ ] The actual support email address to put in the footer.
- [ ] The exact Stripe Payment Link URL, once created in the dashboard
      (a manual step outside this repo).
