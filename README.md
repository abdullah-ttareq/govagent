# GovMind

A general-purpose AI assistant for government employees, built to run inside an
organization's own infrastructure. Employees ask questions in Arabic and get
answers grounded in their organization's own documents — every answer cites the
files it came from.

Every employee uses the same general agent. What differs between them is only
their account, their conversations, their files, and their permissions.

> **This is a graduation project at MVP stage, not a production-ready system.**
> It contains no real government data and no real credentials.

---

## Why this exists

Government organizations can't send internal documents to a public AI service.
GovMind is built around that constraint:

- **The model can run entirely on-premise.** With `lmstudio`, `llamacpp`, or
  `local`, no conversation text ever leaves the organization's network. A cloud
  provider (`livekit`) exists for demos, and the app says so explicitly on screen
  before the user types a character.
- **Data is isolated per organization by construction.** `organization_id` does
  not appear in any request body — it is read from the access token alone.
- **Secrets never leave the server.** The web app, the browser extension, and the
  installer bundle contain no provider keys, no database keys, and no storage
  credentials.

---

## How it works

There are two ways an employee reaches the assistant.

**A. Server deployment (the organization hosts it).** Employees open an
Arabic RTL web app, installable as a PWA, that talks to a FastAPI backend on the
organization's server.

```
Browser (PWA)  ──HTTPS──▶  FastAPI backend  ──▶  Model provider (local or on-prem)
                                │
                                └──▶  Data store (memory / Oracle / Supabase)
```

**B. Per-device product (subscription-based).** A browser extension handles setup
only — sign in, check the subscription, activate the device, download the
installer. The assistant itself then runs as a local Windows app.

```
┌──────────────────────┐         ┌──────────────────────────────────┐
│  Browser extension   │         │  Hosted backend (control plane)  │
│  • sign in           │──HTTPS─▶│  • Supabase (service_role)       │
│  • subscription      │         │  • issues installation tokens    │
│  • one-time token    │         │  • signs Azure SAS links         │
│  • download installer│         │  • single-device activation      │
└──────────┬───────────┘         └──────────────┬───────────────────┘
           │ 127.0.0.1 (token, once)            │ HTTPS
           ▼                                     ▼
┌────────────────────────────────┐        ┌─────────────────┐
│  GovMind Runtime (client PC)   │        │  Azure Blob     │
│  • device identity (DPAPI)     │───SAS─▶│  • installer    │
│  • downloads & verifies model  │        │  • model file   │
│  • supervises llama-server     │        └─────────────────┘
│  • local API on 127.0.0.1 only │
└────────────────────────────────┘
```

The extension never reads a page, never sends text to a model, and never asks the
user for a URL, a server address, or an API key.

---

## Features

- **Arabic RTL chat** with conversations saved server-side and cited sources
- **RAG over the organization's files** — upload `.pdf`, `.docx`, `.txt`; content
  is chunked, embedded, and searchable within the organization only
- **Per-organization data isolation**, enforced by tests that fail if anyone ever
  reintroduces `organization_id` into a request
- **Pluggable model provider** — mock, LM Studio, llama.cpp, Oracle OCI, LiveKit
- **Pluggable data store** — in-memory, Oracle, or Supabase/PostgreSQL with RLS
- **Roles and accounts** — organization admins manage employees; deactivation
  instead of deletion, so history keeps its owner
- **Subscriptions and seats** — checked on login *and* on every protected request
- **Append-only audit log** — no update path, no delete path
- **Single-device activation** per subscription, enforced by a partial unique
  index in the database rather than a check in code
- **Unified Arabic error envelope** across every route, with stack traces kept in
  the server log only

---

## Repository layout

```
govagent/
├── frontend/     Next.js 16 web app — Arabic RTL, PWA, Tailwind 4
├── backend/      FastAPI service — API, providers, RAG, data stores
├── runtime/      GovMind Runtime — local Windows app, packaged with PyInstaller
├── extension/    Manifest V3 browser extension — plain HTML/CSS/JS, no build step
├── installer/    Inno Setup script and PowerShell build pipeline
├── database/     Oracle schema and ordered Supabase migrations
├── docs/         Architecture, install guide, test checklist, demo script
├── mock-data/    Seed organizations, users, and sample files
└── .env.example  Every supported variable, with no real values
```

---

## Requirements

- Node.js 20 or newer
- Python 3.11 or newer
- Chrome or Edge, to try the extension

Local development needs no external service: no database, no API keys, no cloud
account.

---

## Quick start

```bash
cp .env.example .env
```

The defaults are enough to run locally. Leave the Oracle, OCI, Supabase, Azure,
and LiveKit fields empty.

**1. Backend**

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

On Windows, replace `.venv/bin/` with `.venv/Scripts/`.

- Health check: <http://localhost:8000/health>
- Swagger docs: <http://localhost:8000/docs>

**2. Frontend**

```bash
cd frontend
npm install
npm run dev
```

The app runs on <http://localhost:3000>. Start the backend first so chat works.

**3. Extension** (optional)

1. Open `chrome://extensions` in Chrome or Edge.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select the `extension` folder.

Sign in with any seeded account — the password for all of them is the
`DEV_SEED_PASSWORD` value in your `.env`:

| Email | Role | Organization | Subscription |
| ----- | ---- | ------------ | ------------ |
| `admin@digital-services.test` | admin | هيئة الخدمات الرقمية | active |
| `n.alharbi@digital-services.test` | employee | هيئة الخدمات الرقمية | active |
| `admin@urban-planning.test` | admin | مركز التخطيط العمراني | active |
| `admin@national-archive.test` | admin | هيئة الأرشيف الوطني | **expired** |

Two active organizations prove isolation; the third is expired on purpose so the
subscription-expiry path can be tested.

---

## Configuration

### Model provider

Selected by a single variable in `.env`:

| Value | Description |
| ----- | ----------- |
| `mock` | **Default.** Runs with no database and no credentials; returns a generic test reply. |
| `lmstudio` | A model loaded in [LM Studio](https://lmstudio.ai) on the same machine. Local HTTP, OpenAI-compatible, no API key. |
| `llamacpp` | A model inside GovMind Runtime, supervised directly. LM Studio not required. |
| `local` | A model inside the organization's server — future interface. |
| `oracle` | OCI Generative AI. Needs `OCI_*` variables and an OCI identity on the server. |
| `livekit` | ⚠️ **The only cloud provider.** Conversation text leaves the machine. |

```env
MODEL_PROVIDER=mock
```

An unsupported value produces a clear error listing the accepted ones. The chosen
provider goes through the same chat path either way: RAG, sources, isolation, and
conversation history behave identically.

Organizations can also pick their own provider, stored in the database and read
in preference to `MODEL_PROVIDER`. Only the provider *name* is stored — never
keys or secrets.

#### LM Studio setup

1. Install [LM Studio](https://lmstudio.ai) and open it.
2. In **Discover**, find and download your model.
3. In **Developer** (or Local Server), start the server on port `1234` and make
   sure the model is **Loaded**, not just downloaded.
4. Verify: <http://127.0.0.1:1234/v1/models> should return the model.
5. Set the variables below, restart the backend, and send a message. The
   `provider` field in the response will read `lmstudio`.

```env
MODEL_PROVIDER=lmstudio
LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
LM_STUDIO_MODEL=google/gemma-4-e4b
LM_STUDIO_TIMEOUT_SECONDS=300
LM_STUDIO_MAX_TOKENS=1500
LM_STUDIO_API_KEY=
```

> **Timeout and token cap are linked.** Local generation time scales with tokens
> produced, so raising `LM_STUDIO_MAX_TOKENS` without raising
> `LM_STUDIO_TIMEOUT_SECONDS` means timing out mid-answer.
>
> **Reasoning models need a higher cap.** They spend a large share of the budget
> on internal reasoning the user never sees. Measured on `google/gemma-4-e4b`:
> 509 reasoning tokens before the first visible character, so a cap of `512`
> returned an empty answer while `1500` returned a complete one.
>
> **Inside Docker**, a container can't reach the host's `127.0.0.1`. Use
> `LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1`. Running the backend
> directly needs no change.

### Data store

Selected by `DATA_STORE`:

| Value | Store | Schema |
| ----- | ----- | ------ |
| `memory` (default) | In-process, seeded with test organizations. Not durable. | — |
| `oracle` | Oracle tables | `database/schema.sql` |
| `supabase` | Supabase/PostgreSQL with RLS | `database/supabase/` |

Neither database is needed to try the project — connections are lazy and nothing
is touched until its variables are set.

Supabase migrations apply **in order**, and each is safe to re-run:

| # | File | Purpose |
| - | ---- | ------- |
| 0001 | `0001_govmind_supabase.sql` | Core tables and RLS policies |
| 0002 | `0002_installation_sessions.sql` | Subscriptions and installation sessions |
| 0003 | `0003_registration.sql` | Individual account registration |
| 0004 | `0004_device_replacement.sql` | Atomic device replacement |
| 0005 | `0005_device_credentials.sql` | Device credentials |

---

## Security model

**Organization isolation.** The organization is derived from the access token
only. Reaching for another organization's record returns **404 with no body** —
not 403, because "forbidden" would confirm the record exists, and that is itself
information about another organization.

**Email is a system-wide unique identity.** Login looks up by email *before* the
organization is known, so a duplicate across two organizations would force the
system to guess. The uniqueness is case-insensitive and enforced by an index.

**Passwords** are stored bcrypt-hashed only — never in plaintext in a database, a
log, or a response.

**Provisioning a new organization** is an installation act, not an in-app one:
there is no user inside the new organization to authorize it. It is guarded by
`PROVISIONING_KEY` in an `X-Provisioning-Key` header instead of an access token,
and creates the organization and its first admin together. The key is
**mandatory in every environment** — leaving it empty disables the route with a
503 rather than opening it.

**Subscription renewal** is guarded by the provisioning key too, not by an
organization admin — otherwise an admin could grant themselves unlimited seats.

**Uploaded files** are stored under a random name; the name the employee sent is
kept as metadata only, so a filename like `../../.env` never reaches a path.

**Two secrets never leave the server**, because either one in the frontend or the
extension would collapse the whole isolation model:

- `SUPABASE_SERVICE_ROLE_KEY` — bypasses RLS entirely
- `AZURE_STORAGE_CONNECTION_STRING` — carries the storage account key

Never commit `.env` or any real key. Only `.env.example` belongs in the
repository, and it must stay free of real values.

---

## Tests

```bash
cd backend && .venv/bin/python -m pytest     # ~660 tests
cd runtime && python -m pytest               # ~190 tests
cd frontend && npm test                      # vitest
cd extension && npm test                     # vitest
```

Several tests exist specifically to prevent regressions rather than to check
features: one reads the whole OpenAPI spec and fails if `organization_id` ever
returns to a request body, another fails if the chat route loses its
authentication requirement.

---

## Documentation

| File | When you need it |
| ---- | ---------------- |
| [`docs/RUNTIME_ARCHITECTURE.md`](docs/RUNTIME_ARCHITECTURE.md) | Trust boundaries and which party holds which secret |
| [`docs/INSTALL_GUIDE.md`](docs/INSTALL_GUIDE.md) | Running the system from scratch on a new machine |
| [`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md) | Deploying on the organization's own server |
| [`docs/MANUAL_TEST_CHECKLIST.md`](docs/MANUAL_TEST_CHECKLIST.md) | Numbered manual pass over every screen |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | Presenting the project in 8–10 minutes |
| [`docs/postman/`](docs/postman/README.md) | Exercising the full API — 42 requests |
| [`extension/README.md`](extension/README.md) | What the extension does and refuses to do |
| [`installer/README.md`](installer/README.md) | Building and signing the Windows installer |

---

## Known limits

- The installer is **unsigned**. Windows will show "unknown publisher", and
  SmartScreen or Smart App Control may block it. Production needs a code-signing
  certificate.
- In a development build, `control_plane_url` is `http://127.0.0.1:8000`, so the
  installer only works on the same machine that runs the backend. Distributing it
  requires a hosted address and a rebuild.
- The in-memory store and the in-memory audit log are **not durable** and reset on
  restart. A real audit trail requires `DATA_STORE=oracle` or `supabase`.
- Hosting has not been finalized. The options under consideration are Oracle
  Cloud, an independent VPS, or the organization's own server.
