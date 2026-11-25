# Google Search Console setup (needed for the live test)

Everything in QuickIndex's Google integration is built and tested against mocked Google responses. To see **real**
results you must create Google credentials. Until then, the Google Index Status page honestly shows
"Google integration is not set up on this server yet." and no Google data is ever invented.

Never commit the client secret, put it in frontend code, or paste it into chat or logs. It lives only in `backend/.env`.

## 1. Create a Google Cloud project and enable the API

1. Open <https://console.cloud.google.com/> and sign in with the Google account that will own the app.
2. Top bar project picker > **New project** > name it (for example `quickindex`) > **Create**, then select it.
3. **APIs & Services > Library**, search **"Google Search Console API"**, open it and click **Enable**.
   (This one API covers sites, sitemaps and the URL Inspection API.)

## 2. Configure the OAuth consent screen ("Google Auth platform")

1. **APIs & Services > OAuth consent screen** (or **Google Auth platform > Branding**).
2. App name `QuickIndex`, user support email, developer contact email.
3. **Audience / User type: External** (use Internal only if you have a Google Workspace organisation and only staff will connect).
4. **Data access > Add or remove scopes** and add exactly:
   - `https://www.googleapis.com/auth/webmasters.readonly` (read-only: properties, inspections, sitemap list)
   - `https://www.googleapis.com/auth/webmasters` (**only** needed for sitemap *submission*; QuickIndex asks for it separately, later, if the customer chooses)
   - `openid` and `.../auth/userinfo.email` (shows which Google account is connected; non-sensitive)
5. **Audience > Test users**: while the app is in **Testing**, add the Google accounts that will try it (up to 100).

> **Important: refresh tokens expire after 7 days while the app's publishing status is "Testing"** (Google's rule for external apps).
> Scheduled rechecks at 3, 7 and 14 days would then break. For real use, move the app to **In production**. Because the
> Search Console scopes are *probably classified as sensitive*, but Google's public pages do not state it clearly: open
> **Data access** in the Cloud Console and read the classification shown next to each scope before planning verification.
> For sensitive scopes Google shows an "unverified app" warning (and caps unverified apps at 100 users) until you complete
> verification: a public homepage and privacy policy on a domain you own, accurate consent-screen text, a justification for each
> scope, and a demo video of the real integration. Plan for this before a public launch.

## 3. Create the OAuth client

1. **APIs & Services > Credentials > Create credentials > OAuth client ID**.
2. Application type: **Web application**. Name: `QuickIndex backend`.
3. **Authorized redirect URIs** (exact match, no wildcards), add:
   - `http://localhost:8000/api/v1/google/callback` (local development)
   - `https://YOUR-API-DOMAIN/api/v1/google/callback` (production; must be HTTPS)
4. Create, then copy the **Client ID** and **Client secret** (the secret is shown in the same dialog and later under Credentials).

## 4. Configure the backend

Generate an encryption key for stored refresh tokens (keep it secret and backed up: losing it means every customer must reconnect):

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add to `backend/.env` (this file is git-ignored):

```
GOOGLE_CLIENT_ID=<client id from step 3>
GOOGLE_CLIENT_SECRET=<client secret from step 3>
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/google/callback
TOKEN_ENCRYPTION_KEY=<key generated above>
FRONTEND_URL=http://localhost:3000
```

**Hosting requirement for the sign-in cookie.** The API sets a short-lived HttpOnly cookie that ties a Google sign-in attempt
to the browser that started it (state is also single-use). The browser only sends it back to the API if the app and the API
are **same-site**, for example `app.example.com` and `api.example.com`, both HTTPS in production. `localhost:3000` and
`localhost:8000` are same-site, so development works unchanged.

**Behind a reverse proxy**, start uvicorn with `--proxy-headers --forwarded-allow-ips=<your proxy's IP>`; otherwise every visitor
shares the proxy's address and the per-IP recovery limit (and logs) become wrong.

Rotating the encryption key: put the new key first and keep the old one after a comma
(`TOKEN_ENCRYPTION_KEY=new,old`); tokens re-encrypt with the new key the next time a customer reconnects.

Restart the backend. `GET /api/v1/google/status` now reports `configured: true`.

## 5. Search Console side

The Google account you connect must be an **owner or full user** of the property in <https://search.google.com/search-console/>
(Domain properties are verified with a DNS record; URL-prefix properties with an HTML file, tag, Analytics or Tag Manager).
Only **verified** properties can be inspected. Backlink pages on other people's sites cannot be inspected; Google only answers for properties you control.

## 6. Live test checklist (do this once credentials exist)

1. Sign in to QuickIndex > **Google Index Status** > **Connect Google Search Console** > approve read-only access.
2. The page shows your Google account and "Read-only". Pick a property (Domain vs URL prefix badges are shown).
3. Add 2 or 3 URLs you own, one you know is indexed and one you know is not. Check each shows Google's own verdict and coverage state.
   Compare against the same URL in Search Console's URL Inspection tool.
4. Add a URL on a different site: it must be rejected as "outside property".
5. Open the **Sitemaps** panel: sitemaps are listed. Click **Grant write access**, approve, then submit a sitemap URL on your property.
6. Click **Disconnect**; confirm access is revoked at <https://myaccount.google.com/permissions>.
7. Revocation test: connect again, remove QuickIndex at <https://myaccount.google.com/permissions>, then press Recheck: the page must show
   "Google access was revoked or expired. Reconnect" and stop inspecting.
8. Scheduled rechecks run at 1, 3, 7 and 14 days (use `GET /targets/{id}/history` to see them). Quota: 2,000 inspections per property per day and 600 per minute are enforced.

## Operational notes

- Access tokens are kept in memory only; refresh tokens are stored encrypted and bound to the owning customer.
- Server logs redact `code=` and `state=` from the OAuth callback URL. Do not add request-body logging.
- The daily quota counter is stored in Appwrite and incremented **atomically with a cap**, so several workers cannot overspend it and a restart
  does not reset it. Counting is per **property**, matching Google's quota. `GSC_MANUAL_RESERVE` (default 200) keeps part of the day free for
  manual rechecks.
- Google does not clearly document when the URL Inspection daily quota resets. QuickIndex assumes midnight Pacific time, but a 429 from Google
  always wins: the property is paused with an escalating delay (2 min, 10 min, 1 h, 6 h, 24 h) that resets after a success.
- The per-minute window is in memory: run exactly one Google worker (`GSC_WORKER_COUNT=1`, on one instance).
- If you run more than one API instance, run the Google worker (`GSC_WORKER_COUNT`) on only one of them, or accept occasional duplicate inspections (rows are claimed with optimistic locking, which is best effort).

## Privacy and Google's API Services User Data Policy

Before real customers connect, publish a privacy policy and consent text that say, in plain language:

- **What is collected:** the connected Google account's email, the list of Search Console properties, and, for URLs the customer chooses
  to track, Google's URL Inspection results and sitemap status. Nothing else is read from Search Console.
- **Why:** only to show the customer whether their own pages are indexed and how that changes over time. The data is not sold, not used for
  advertising, never shown to other customers, and not used to train models.
- **How it is protected:** refresh tokens are encrypted at rest and tied to the owning customer; access is limited to that customer.
- **Retention and deletion:** inspection history is kept until the customer deletes it. The dashboard has two separate controls:
  **Disconnect** (revokes access at Google, keeps history) and **Delete my Google data** (disconnects and erases tracked URLs and history).
  Customers can also revoke access at <https://myaccount.google.com/permissions>.
- Request only the scopes you need (read-only by default), and keep the "Limited Use" wording from Google's policy in the policy page.

## Launch checklist

**Required by Google:** Cloud project and consent screen configured; scope classification checked; privacy policy and homepage on a verified domain;
demo video; verification submitted if the scopes are sensitive; production app status (not "Testing") so refresh tokens do not expire after 7 days.
**Security:** same-site HTTPS hosting; `TOKEN_ENCRYPTION_KEY` stored in a secrets manager and backed up; proxy headers configured; one Google worker.
**Operations:** alert on repeated `quota_exhausted` and on connections turning `revoked`; document key rotation; monitor the worker.
**Wording:** the product promises "Google reports indexed", never guaranteed indexing or search visibility. Google's results are stored index data, not a live
test, so the page shows both the time we checked and Google's last-crawl time.

## Phase 5 runbook: live validation with your own Google account

`scripts/google_live_check.py` validates the integration against Google's REAL API. It reads credentials only from `backend/.env`,
masks tokens and secrets in everything it prints, and never claims a result it did not get from Google.
(Its own behaviour is covered by tests against a mocked Google; those tests are not live results.)

1. Do sections 1 to 4 above. `.env` already has empty `GOOGLE_CLIENT_ID=` and `GOOGLE_CLIENT_SECRET=` lines and a generated `TOKEN_ENCRYPTION_KEY`: paste the two Google values in.
2. From `backend`: `.venv\Scripts\python scripts\google_live_check.py preflight`. Every line must be PASS. The last check asks Google itself whether it
   accepts your client id and secret (it should answer `invalid_grant` for a fake code, which means the client is valid; `invalid_client` means a wrong id/secret;
   `redirect_uri_mismatch` means the callback is not registered exactly as `http://localhost:8000/api/v1/google/callback`).
3. Start the backend (`uvicorn app.main:app --reload`, one process, `GSC_WORKER_COUNT=1`) and the frontend (`npm run dev`).
4. In your browser: register or sign in to QuickIndex > **Google Index Status** > **Connect Google Search Console** > sign in to Google and approve **read-only** access.
   You are returned to `/dashboard/google?connected=1`. Choose your property. (Do not request write access yet.)
5. Find your QuickIndex user id (Appwrite console > Auth > Users, the `$id` of your account) and run, one at a time, from `backend`:

```
python scripts\google_live_check.py --user-id <ID> status
python scripts\google_live_check.py --user-id <ID> properties
python scripts\google_live_check.py --user-id <ID> inspect https://YOUR-SITE/a-page-you-know-is-indexed https://YOUR-SITE/a-page-you-know-is-NOT-indexed
python scripts\google_live_check.py --user-id <ID> refresh
python scripts\google_live_check.py --user-id <ID> sitemaps
python scripts\google_live_check.py --user-id <ID> schedule https://YOUR-SITE/some-other-page
```

   Compare each `inspect` result with the same URL in Search Console's URL Inspection tool. Check `coverageState`, `lastCrawlTime` and the canonical URLs match.
6. Sitemap submission (only when you really want to submit one): in the web app click **Grant write access**, approve the extra permission, then submit a sitemap you own.
7. Finish with `disconnect` (revokes at Google and confirms the old refresh token is rejected), reconnect in the app if you want to continue, and finally
   `delete-data` (removes the connection, tracked URLs and history; it prints what is left, which must be nothing).

Quota: `inspect` and `schedule` use a handful of the 2,000 daily units. Do not loop them. Send the redacted output back; do not paste your client secret.
