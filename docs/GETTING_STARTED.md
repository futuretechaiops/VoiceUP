# Getting started (no coding or Git experience needed)

This guide gets the AI Sales Concierge running on your own computer and shows the chat widget working on a pretend customer website. It takes about 30 minutes the first time, most of it installing tools.

**What you will see:** a demo website for "Demo Estates" with a round button in the corner. Clicking it opens a chat. The demo company has two small built-in pages, so you can ask "What are your tenant fees?" and see an answer with a source link, then try the call-back form. Without an AI key the answer quotes the matching page; to put this on a real website, follow `docs/FUTURETEC_GO_LIVE.md`.

## 1. Install four free tools (once)

| Tool | What it is for | Get it |
| --- | --- | --- |
| Git | Downloads the code | https://git-scm.com/downloads |
| Node.js 22 or newer | Builds the widget | https://nodejs.org (choose "LTS") |
| Python 3.12 or newer | Runs the server | https://www.python.org/downloads |
| Docker Desktop | Runs the database | https://www.docker.com/products/docker-desktop (open it once so it says "running") |

**Windows users:** also install "WSL" so you have a Linux-style terminal. Open the Start menu, search for **PowerShell**, right-click it, choose *Run as administrator*, type `wsl --install` and press Enter, then restart the computer. From then on, open the app called **Ubuntu** for every command below, and install Git, Node and Python *inside Ubuntu* by following their Linux instructions (Docker Desktop stays on Windows; turn on its "WSL integration" setting). On a Mac, use the app **Terminal**.

Check the installs. Paste each line into the terminal and press Enter; each should print a version number:

```bash
git --version
node --version
python3 --version
docker --version
```

## 2. Download the code

```bash
git clone https://github.com/futuretechaiops/VoiceUP.git
cd VoiceUP
git checkout feat/widget-text-session
```

(Once the work has been merged you can skip the third line.)

## 3. Set up and start everything

Run these one at a time. Wait for each to finish before the next.

```bash
cp .env.example .env
make install
make db
make migrate
make seed-demo
```

`make db` starts the database in Docker (the first run downloads it, so be patient). `make seed-demo` creates the demo company, a demo assistant called Ava and the approved demo website addresses.

Now start two things, **each in its own terminal window** (open a second terminal window, then `cd VoiceUP` in it too):

```bash
# terminal 1: the server
make dev-api
```

```bash
# terminal 2: the pretend customer website
make demo-site
```

Leave both running.

## 4. Try it

1. Open **http://localhost:8080** in your browser.
2. Click the green round button at the bottom right.
3. Read the notice: the visitor is told it is an AI. Click **Start conversation**.
4. Type a question and press Send. You get a labelled test reply.

Also open **http://localhost:8000/docs** to see every server function. Those are for developers, so just look.

## 5. See the security check work

The server only talks to websites the customer has approved. In a **third** terminal:

```bash
cd VoiceUP/apps/widget/test-site && python3 -m http.server 8081
```

Open **http://localhost:8081**, click the button, then **Start conversation**. You should see *"This website is not approved to use this assistant."* Same page, same widget, different address: refused. Press `Ctrl+C` in that terminal to stop it.

## 6. Put the widget on your own test page

1. Make a file `mypage.html` anywhere with any content, plus this one line before `</body>`:

   ```html
   <script async src="http://localhost:8080/widget.js" data-agent-id="agt_demo_public" data-api-base="http://localhost:8000"></script>
   ```

2. Serve it from a folder on port 9000: `python3 -m http.server 9000`, then open http://localhost:9000/mypage.html. It is refused, because `localhost:9000` is not approved yet.
3. Approve it (paste into any terminal, from the VoiceUP folder):

   ```bash
   H='-H X-Dev-User-Id:d0000000-0000-4000-8000-000000000002 -H X-Dev-Tenant-Id:d0000000-0000-4000-8000-000000000001 -H X-Dev-Role:customer_admin -H X-Dev-Auth-Secret:local-development-only'
   ID=$(curl -s -X POST localhost:8000/api/v1/domains $H -H 'Content-Type: application/json' -d '{"hostname":"localhost:9000"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
   curl -s -X POST localhost:8000/api/v1/domains/$ID/verify $H
   ```

4. Reload the page: it works. That is exactly what a real customer does with their real address, in production through DNS verification, which is built in a later phase.

## 7. Check everything is healthy (optional)

```bash
make test-api     # 71 automated checks against a real database
```

## Stop and tidy

Press `Ctrl+C` in each terminal running `make dev-api` or `make demo-site`. To stop the database: `docker compose down`.

## If something goes wrong

| Message or symptom | What to do |
| --- | --- |
| `make: command not found` | Windows: you are not in the Ubuntu app. Mac: run `xcode-select --install`. |
| `Cannot connect to the Docker daemon` | Open Docker Desktop and wait until it says it is running, then retry. |
| `port is already allocated` or `address already in use` | Something else uses that port. Close it, or restart the computer. |
| `make migrate` fails with "password authentication failed" | The database was created before the setup files existed. Run `docker compose down -v` (this deletes the demo database), then `make db`, `make migrate`, `make seed-demo` again. |
| Button appears but clicking Start says "unavailable" | `make dev-api` is not running, or crashed. Look at its terminal. |
| Page shows no button | `make demo-site` is not running, or you opened a different address than `http://localhost:8080`. |

## Keep building with Claude

Open a new Claude Code session, attach the VoiceUP repository, and ask for the next step, for example: *"Read docs/PROJECT_SPECIFICATION.md and the plan, then build WP2: agent versions and publishing, with tests, on a new branch."* Claude pushes each piece to GitHub as a branch for you to review and merge.
