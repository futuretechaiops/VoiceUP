# FutureTec go-live guide: AI assistant on futuretecinfo.com

This guide puts a chat assistant on **https://futuretecinfo.com**. It answers visitors' questions from your own website, builds its own knowledge base by reading every page, and, when a visitor asks for a call back, emails their **name, phone number and email address** to **info@futuretecinfo.com**.

It is written for someone new to servers and code. Allow about 90 minutes the first time.

## What you get, and what you do not

| Included | Not included |
| --- | --- |
| Chat bubble on every page of the site | **Voice calls.** This build is text chat only. Phone/voice is a later phase. |
| Answers drawn only from your website, with links to the pages used | Answers about things your website does not say (it says so and offers a call back) |
| Knowledge base built by reading your site, refreshed on a schedule | Reading PDFs, or pages behind a login |
| Call-back form with a consent tick-box; details emailed to info@futuretecinfo.com | A dashboard. You manage it with a few typed commands (below). |

Because this is a demo for prospective customers, the safest way to show it is the script in section 8.

## How the pieces fit

```
Visitor's browser on futuretecinfo.com
   │  loads one script (widget.js) from  https://voice.futuretecinfo.com
   ▼
Your small server (a "VPS") running this project in Docker
   ├─ finds the best matching pages in the knowledge base
   ├─ asks Claude to write a short answer using only those pages
   └─ on a call-back request, emails info@futuretecinfo.com
```

The website itself is not changed except for **one line** added to it (section 6).

## 1. What you need before you start

1. **A server (VPS).** Any Linux server with 2 GB memory or more and Docker, for example DigitalOcean, Hetzner or Linode (about £6 to £10 a month). Choose **Ubuntu 24.04**. When you create it, you will be given an IP address (four numbers like `203.0.113.10`).
2. **Access to your domain's DNS settings** (wherever futuretecinfo.com is managed: your domain registrar or hosting control panel).
3. **An Anthropic API key** from https://console.anthropic.com/ (create an account, add a few pounds of credit, then *API keys* → *Create key*). Typical cost for a demo is pennies per conversation. The setting `DAILY_AI_MESSAGE_CAP` stops runaway spending.
4. **Email sending details (SMTP)** for an address that may send mail for futuretecinfo.com. Your email provider's help pages call it "SMTP settings". You need the host name, port (usually 587), username and password. Gmail and Microsoft 365 need an "app password" rather than your normal one.
5. **Access to edit the website.** The site appears to be built with Lovable. See section 6.

## 2. Point a name at the server

Visitors' browsers need an address for the assistant. Use a sub-domain of your own, for example `voice.futuretecinfo.com`.

In your DNS settings add one record:

| Type | Name | Value |
| --- | --- | --- |
| A | `voice` | your server's IP address |

Wait 5 to 30 minutes. Check it from your computer: `ping voice.futuretecinfo.com` should show your server's IP.

## 3. Set up the server

Connect to the server (the provider shows a "Console" button, or from a terminal: `ssh root@YOUR_SERVER_IP`). Paste these lines one at a time:

```bash
curl -fsSL https://get.docker.com | sh          # installs Docker
git clone https://github.com/futuretechaiops/VoiceUP.git
cd VoiceUP
git checkout FutureVoiceUP                       # the branch with this demo
cd deploy
cp env.production.example .env
nano .env                                        # fill in every blank (see below), then Ctrl+O, Enter, Ctrl+X
```

Fill in `.env`:

- `API_DOMAIN`: `voice.futuretecinfo.com`
- `OWNER_DB_PASSWORD`, `APP_DB_PASSWORD`, `WIDGET_SIGNING_KEY`: run `openssl rand -hex 24` (and `openssl rand -hex 32` for the signing key) and paste each result. Use a different value for each.
- `ANTHROPIC_API_KEY`: your key.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`: from your email provider.
- Leave `APP_ENV=production`, `DEV_AUTH_ENABLED=false`, `ADMIN_API_ENABLED=false` and `ALLOW_MANUAL_DOMAIN_VERIFICATION=false` as they are.

Start everything (the first build takes 5 to 10 minutes):

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps        # all services should say "running" or "exited 0" for migrate
```

Open `https://voice.futuretecinfo.com/widget.js` in your browser. If you see a block of JavaScript, the server is up and the HTTPS certificate was issued automatically.

## 4. Create the company record

This registers futuretecinfo.com as an approved site and sets where leads are emailed:

```bash
docker compose -f docker-compose.prod.yml exec api python -m concierge.cli bootstrap-tenant \
  --name "FutureTec" --site https://futuretecinfo.com \
  --notify-email info@futuretecinfo.com --agent-name Ava
```

It prints a **Tenant id** and a **Public agent id** (starts with `agt_`). Copy both. Only `futuretecinfo.com` and `www.futuretecinfo.com` can use this assistant. Any other website that copies your script is refused.

## 5. Build the knowledge base (read the whole website)

```bash
docker compose -f docker-compose.prod.yml exec api python -m concierge.cli crawl \
  --tenant-id PASTE_TENANT_ID --site https://futuretecinfo.com
```

It follows links across the site, respects `robots.txt`, stays on futuretecinfo.com, and uses a built-in browser when pages are built with JavaScript. It prints how many pages it indexed. **If it says 0 pages**, see Troubleshooting.

Check what it learned by asking it directly:

```bash
docker compose -f docker-compose.prod.yml exec api python -m concierge.cli ask \
  --tenant-id PASTE_TENANT_ID "What services do you offer?"
```

**Keep it fresh.** When you change the website, re-run the same crawl command. Unchanged pages are skipped, edited pages are updated and deleted pages are forgotten. To do it automatically every night, run `crontab -e` and add (adjust the path, and paste your tenant id):

```
30 2 * * * cd /root/VoiceUP/deploy && docker compose -f docker-compose.prod.yml exec -T api python -m concierge.cli crawl --tenant-id PASTE_TENANT_ID --site https://futuretecinfo.com >> /var/log/voiceup-crawl.log 2>&1
```

## 6. Add the assistant to the website

Add this one line just before the closing `</body>` of the site's main HTML page (`index.html`). Use your own **Public agent id**:

```html
<script async src="https://voice.futuretecinfo.com/widget.js" data-agent-id="agt_PASTE_YOURS"></script>
```

**If the site is built with Lovable:** Lovable projects are single-page apps with one `index.html`. Either:

- **Ask Lovable's chat:** *"In index.html, add this line just before the closing </body> tag, exactly as written: `<script async ...>`"* (paste your full line), then publish; or
- **Edit through GitHub:** if the project is connected to GitHub, open `index.html` in the repository, paste the line before `</body>`, and commit. Lovable publishes the change.

If the site is hosted somewhere else (WordPress, Wix, Squarespace, cPanel), look for a "custom code", "header/footer scripts" or "insert code before `</body>`" setting and paste the same line there.

I could not test against your live site or Lovable from here, so check it as in section 7.

## 7. Test it (10-minute checklist)

1. Open https://futuretecinfo.com in a private window. A round button should appear at the bottom right.
2. Click it, choose **Start conversation**, and ask something your website answers (for example, "What do you do?"). The reply should match your site, with a **Sources** link underneath.
3. Ask something it should not know ("What is the weather?"). It should say it could not find it and offer a call back, not make something up.
4. Click **Request a call back**. Try submitting without the tick-box (it must refuse). Then fill in a test name, a real phone number and your own email, tick the box and send.
5. Within about a minute, **info@futuretecinfo.com** should receive "New website enquiry: <name>" with the name, phone number, email address, the page, the consent wording and the recent chat. Replying to it replies to the visitor.
6. If no email arrives: `docker compose -f docker-compose.prod.yml logs api | tail -50`, check the spam folder, and check the SMTP details in `.env`. After fixing `.env`, run `docker compose -f docker-compose.prod.yml up -d` and then `docker compose -f docker-compose.prod.yml exec api python -m concierge.cli outbox-send` to resend anything waiting. Emails that fail are retried automatically and are never lost silently.

## 8. Showing it to potential customers

A short script that works well:

1. "This chat reads our website, so I never write the answers by hand." Ask two or three questions about FutureTec's services; point at the **Sources** link.
2. "It doesn't make things up." Ask something unrelated and show the honest "I couldn't find that" reply.
3. "It captures the lead." Click **Request a call back**, fill it in, and show the email landing in the inbox with the conversation attached.
4. "Your version would be trained on *your* site in minutes." Offer to run the crawl on their website (`bootstrap-tenant` and `crawl` with their address) as a follow-up.

Be upfront that voice calling is the next phase.

## 9. Privacy and your responsibilities

- The widget tells visitors they are talking to an AI, and the call-back form asks for **explicit consent** before storing name, phone and email. Consent wording and time are stored with each request.
- Conversations and call-back details are stored in your database on your server. Decide how long to keep them and tell visitors in your privacy policy (the `PRIVACY_URL` setting is reserved for linking it in the widget). If you serve visitors in the UK or EU, your privacy policy should mention this assistant, the AI provider (Anthropic, which receives the visitor's question and the website text used to answer it) and the email provider. I am not a lawyer, so have your adviser review this.
- The assistant is instructed not to ask for personal details in the chat; only the form collects them (visitors can still type anything, so keep this in your privacy notice).

## 10. Costs and safety limits

- Server: roughly £6 to £10 a month.
- AI: set by use. `DAILY_AI_MESSAGE_CAP=300` caps AI answers per day; after the cap, the assistant falls back to quoting the best page rather than failing.
- Abuse limits are built in: requests per minute, at most 5 call-back forms per hour per visitor address, a hidden spam trap field, and one call-back per conversation.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Crawl says "No pages were indexed" | The site may block automated visitors or `robots.txt` may disallow crawling. Run it again with `--mode browser`. Read the "skipped" lines it prints for the reason. |
| Bubble does not appear | Open the browser's developer console (F12). A message about *Content-Security-Policy* means the site restricts scripts; allow `https://voice.futuretecinfo.com` for `script-src` and `connect-src`. A 404 on `widget.js` means the script URL or DNS is wrong. |
| Chat says "This website is not approved" | The page's address is not `futuretecinfo.com` or `www.futuretecinfo.com`. Re-run `bootstrap-tenant` with `--extra-domain other.example` for an additional address (for example a staging site). |
| Answers just quote a page | `ANTHROPIC_API_KEY` is missing or invalid, or the daily cap was reached. Check `docker compose ... logs api`. |
| Certificate error | DNS has not propagated yet, or ports 80 and 443 are blocked by the server's firewall. |
| Site changed but answers did not | Run the crawl command again (section 5). |

## What was and was not tested

Tested automatically (116 tests, including real PostgreSQL, a real Chromium browser and a real SMTP server run locally): crawling static and JavaScript-built sites, knowledge-base search and tenant isolation, the answer logic including prompt-injection handling, call-back validation, consent, spam trap and rate limits, email delivery with retries, the production-safety checks on settings, and the full flow in a browser.

**Not tested from where this was built, so verify on your server:** the Docker build and docker-compose files; Caddy's HTTPS certificate; sending through *your* email provider; reading *your live* futuretecinfo.com; the Lovable steps; and the AI answers against the real Anthropic service (the request format was checked against a local stand-in, and the answer wording can only be judged with a real key). Use the checklist in section 7.
