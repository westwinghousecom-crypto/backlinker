# QuickIndex Privacy Policy

**DRAFT: requires legal review before launch.** Text in [BRACKETS] must be completed by the operator. This draft describes what the software does today; if the software changes, this policy must change with it.

**Effective date:** [DATE]
**Operator:** [LEGAL NAME OF THE BUSINESS OR PERSON RUNNING QUICKINDEX], [POSTAL ADDRESS]
**Privacy contact:** [PRIVACY EMAIL ADDRESS]

QuickIndex helps you get backlink pages noticed by search engines, checks whether a page is technically able to be indexed and whether it really links to your site, and, for sites you own, shows what Google itself reports about whether a page is indexed.

## 1. What we collect

- **Account details.** Your email address, your name (if you give one) and your password. Passwords are handled by our sign-in provider (Appwrite) and are stored as a one-way hash; we never see or store your password in readable form.
- **URLs you submit and the results.** Lists of URLs you ask us to submit for indexing, the status of each submission, backlink-check batches (the URLs, the website you said they should link to) and the findings for each page (HTTP status, redirects, robots.txt and noindex results, canonical URL, whether your link was found, its anchor text and link type).
- **Sharing choice.** Whether you switched on a public feed for a batch. It is off unless you turn it on.
- **Google Search Console data (only if you connect Google).** The email of the Google account you connected, the access level you granted, which Search Console property you picked, the URLs you ask us to track, Google's URL Inspection results for those URLs (verdict, coverage state, last crawl time, canonical URLs, robots.txt and indexing states) and the history of how those results changed, and the sitemaps listed for your property.
- **Google sign-in credentials.** Google gives us a refresh token that lets us keep checking while you are away. We store it encrypted and use it only for your connection. We never show it to you or to anyone else.
- **Technical data.** Our servers see your IP address and request details when you use the service. We use them to keep the service secure (for example, rate limits and abuse prevention). Server logs hide one-time sign-in codes and are not used for advertising.

We do not collect payment details (QuickIndex does not currently take payments) and we do not use advertising or third-party analytics cookies.

## 2. Why we use it

Only to run the features you ask for: sending and checking your URLs, showing results and history, connecting to Google Search Console on your behalf, keeping your account secure, answering support requests and meeting legal obligations. We do not sell personal data and we do not use it for advertising.

## 3. Google user data (Limited Use)

If you connect Google Search Console, QuickIndex asks for read-only access to your Search Console data by default. A separate, optional permission is requested only if you choose to submit a sitemap.

- We use Google data only to show you, inside QuickIndex, what Google reports about the pages and sitemaps you chose.
- We do not sell Google user data, do not use it for advertising, do not use it to train general AI models, and do not allow humans to read it except where you ask for support, it is needed for security or to follow the law, or the data is aggregated and anonymised.
- One customer's Google data is never shown to another customer.
- QuickIndex's use and transfer of information received from Google APIs to any other app will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.
- You can disconnect at any time in the app (this tells Google to revoke our access and stops all checks), and you can also remove access at https://myaccount.google.com/permissions. "Delete my Google data" in your account page also erases your tracked URLs and inspection history.

## 4. Who handles your data

- **Appwrite Cloud** hosts our user accounts and database (region: [REGION, for example Frankfurt]). Appwrite acts as our service provider. Appwrite also sends the password-reset and email-verification emails.
- **Our hosting provider** [HOSTING PROVIDER AND REGION] runs the QuickIndex application.
- **Search engines and indexing services.** When you submit URLs for indexing, we send those URLs (and our indexing key) to the IndexNow service and the search engines that take part in it, such as Bing and Yandex. Anything you submit should be a URL you are comfortable sharing with them.
- **Pages you ask us to check.** To check a backlink page we fetch it from our servers, like a browser would. The site you check will see a request from QuickIndex.
- **Google** receives the requests we make on your behalf when you connect Search Console.
- **Public feeds.** If you switch on a public feed for a batch, anyone with its link can read the list of URLs in that batch. Switch it off to make it private again.
- We may disclose data if the law requires it. If QuickIndex is sold or merged, we will tell you before your data is transferred to a new owner.

We do not use any other third party to process your data. [ADD ANY ADDITIONAL PROCESSORS YOU INTRODUCE, SUCH AS EMAIL, ERROR TRACKING OR HOSTING SERVICES.]

## 5. Cookies and similar storage

- **Sign-in session.** Appwrite stores your session in a cookie or in your browser's local storage so you stay signed in. This is essential for the service.
- **Google connection cookie.** When you start connecting Google, we set a short-lived (10 minute), HttpOnly cookie named `qi_oauth_binding`. It exists only to make sure the sign-in is completed by the same browser that started it, and it is removed when the connection finishes.
- We do not use advertising or tracking cookies.

## 6. How long we keep data

These are automatic limits. Our software removes older data once a day.

| Data | Kept for |
| --- | --- |
| Backlink-check batches and their results | 90 days after they were created |
| Finished indexing submissions (completed, submitted or failed) and their public-feed setting | 90 days after they were created |
| Google inspection history | 365 days after each entry was created |
| One-time sign-in security codes for the Google connection | About 1 hour |
| Google daily usage counters | 7 days |
| Tracked Google URLs, your Google connection and your account details | Until you delete them or your account |

Submissions that are still waiting or in progress are not removed by the automatic cleanup. We keep encrypted backups of our database for disaster recovery for [BACKUP RETENTION PERIOD]. Data you delete may remain in those backups until they expire.

## 7. Your choices and rights

- **Export.** In Account, choose "Export my data" to download everything we store about you as a file. The Google refresh token is never included.
- **Delete Google data.** In Account or Google Index Status, choose "Delete my Google data".
- **Delete your account.** In Account, choose "Delete account" and type DELETE. We revoke Google access, erase the data listed in section 1 and remove your account.
- **Other rights.** Depending on where you live you may also have the right to access, correct, restrict or object to our use of your data and to complain to your data protection authority. Contact us at [PRIVACY EMAIL ADDRESS]. [ADD LEGAL BASIS FOR PROCESSING AND INTERNATIONAL TRANSFER WORDING REQUIRED IN YOUR JURISDICTION, FOR EXAMPLE GDPR ARTICLES.]

## 8. Security

We use HTTPS, encrypt Google refresh tokens, separate each customer's data so that one customer cannot read another's, limit how often sensitive actions can be repeated, and block our page checker from reaching private or internal networks. No system is perfectly secure; if we learn of a breach that affects you we will tell you as the law requires.

## 9. Children

QuickIndex is not for children under [AGE, FOR EXAMPLE 16] and we do not knowingly collect their data.

## 10. Changes

If we make material changes, especially to how Google user data is used, we will tell you in the app or by email before they take effect. The date at the top shows when this policy last changed.

## 11. Contact

[OPERATOR NAME], [POSTAL ADDRESS], [PRIVACY EMAIL ADDRESS]. [DATA PROTECTION OFFICER OR EU/UK REPRESENTATIVE, IF REQUIRED.]
