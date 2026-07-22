# Samvid

**Contract intelligence from inbox to signature.**

Samvid is an AI-powered contract workspace for legal, procurement, finance, and
operations teams. Forward a contract by email or upload it from the browser;
Samvid reads every page, identifies material terms and risks, preserves the
supporting evidence, and keeps review and signing activity moving in one
accountable workflow.

Samvid is the customer-facing product. `contractmate` is the internal Python
package and operator CLI used by the API and background worker.

## The Product

Contract work is often split across inboxes, shared drives, chat threads, and
spreadsheets. Samvid brings that work into a single searchable record so teams
can answer three questions without relying on memory:

- What does this contract require?
- What needs attention before it moves forward?
- Who owns the next action?

Every contract can enter through the channel people already use, return with a
plain-language review, and continue through a visible signing workflow.

## What Samvid Does

### Intake from email or the workspace

Forward PDF, DOCX, or TXT contracts to the configured Samvid inbox, or upload
them directly from the Contracts workspace. Samvid validates each file, records
its SHA-256 identity, stores the original privately, and creates a durable
contract record before processing begins.

### Read the complete document

Samvid extracts text from digital documents and uses Sarvam OCR for scanned
PDFs. Large OCR jobs are split into supported page groups and reassembled with
their original page numbering, so the review remains traceable to the source.

### Explain terms and risks in plain language

The review identifies parties, dates, obligations, renewal terms, governing
law, indemnities, liability exposure, and other material clauses. Risk findings
include evidence from the document and are validated before they are presented
to the user.

### Keep work moving

Teams can follow contract status from review through signing coordination,
record signer activity, and preserve a chronological event history. Email-led
reviews return to the original thread with a professional summary and a link to
open the contract in Samvid.

### Keep every contract discoverable

The workspace provides contract search, review and signing filters, contract
detail views, source-document access, and a shared signing queue. The browser
experience and email workflow use the same contract record rather than creating
parallel sources of truth.

## Product Experience

- **Contracts:** Search, filter, upload, and monitor every contract in the
  workspace.
- **Review:** Read the summary, parties, key terms, risks, evidence, and next
  actions generated from the document.
- **Document:** Open the stored original through an authenticated API response.
- **Signing:** Create signing requests, assign signers, and record sent, viewed,
  signed, declined, and related workflow events.
- **Email intake:** Send a contract to one address and receive the completed
  review in the same email thread.
- **Account access:** Sign up, verify an email address, sign in, recover a
  password, and access only the authorized Samvid workspace.

## Contract Lifecycle

```text
Email attachment or browser upload
                |
                v
      FastAPI intake and validation
                |
                v
   Private document storage + Neon record
                |
                v
        Durable RabbitMQ review job
                |
                v
       Persistent contract worker
                |
       +--------+---------+
       |                  |
       v                  v
Parsing / Sarvam OCR   Agno / OpenAI review
       |                  |
       +--------+---------+
                |
                v
 Evidence validation + persisted result
                |
       +--------+---------+
       |                  |
       v                  v
 Samvid workspace    Threaded email response
```

The API stores the document and creates the database record before publishing a
job. The worker downloads that exact stored version, verifies its hash, performs
OCR and review, saves the result, and only then acknowledges the RabbitMQ
message. Retry queues and a dead-letter queue protect work from transient or
repeated failures.

## Platform Architecture

| Surface | Technology | Responsibility |
| --- | --- | --- |
| Web workspace | React, TypeScript, Vite | Contract, review, document, signing, and account experiences |
| Authentication | Neon Auth, Better Auth, JWKS | Browser sessions, email verification, password recovery, JWT issuance |
| API | FastAPI, Pydantic | Authorization, contract APIs, uploads, webhooks, signing activity |
| Database | Neon PostgreSQL | Contracts, reviews, versions, signers, events, and webhook idempotency |
| Document storage | Private Vercel Blob or local filesystem | Original contract files and version-safe retrieval |
| Job broker | RabbitMQ / CloudAMQP | Durable review delivery, retry, and dead-letter routing |
| Review worker | Python, Agno, OpenAI | Parsing, structured analysis, evidence validation, and response generation |
| OCR | Sarvam | Text recovery from scanned PDFs |
| Email | Resend | Inbound contract receiving and threaded outbound reviews |
| Delivery | Vercel, GHCR, EC2, GitHub Actions | Web/API hosting, worker images, and persistent processing |

The API and worker are intentionally separate. Vercel handles bursty HTTP
traffic, while the EC2 worker remains available for long-running OCR and model
calls without relying on a serverless request lifetime.

## Trust and Safety

- Private contracts are served through authenticated API routes rather than
  public storage URLs.
- Neon JWTs are verified against branch-specific EdDSA/JWKS keys, issuer,
  audience, expiry, and verified-email state. Samvid then resolves the identity
  to a private account in its own database.
- Resend webhooks are verified from the untouched request body using their Svix
  signature headers.
- Inbound events are idempotent. Completed deliveries are ignored, failed
  deliveries can retry, and stale processing leases can be reclaimed.
- File type, MIME content, size, attachment count, and SHA-256 identity are
  validated before review.
- Evidence validation removes unsupported risk findings before results are
  persisted or emailed.
- Signing actions and status changes are recorded as workflow events.
- Secrets belong in environment-variable stores and must never be committed.

## Signing Scope

Samvid coordinates and tracks signature workflows. It does not place visual
signature fields in documents, verify a signer's legal identity, issue digital
certificates, or execute legally binding electronic signatures. Execution
requires an integration with an e-signature provider.

## Local Development

### Prerequisites

- Python 3.12 or later
- [`uv`](https://docs.astral.sh/uv/)
- Node.js 20 or later
- Docker with the Compose plugin for local PostgreSQL and RabbitMQ

### Install and test the backend

```bash
uv sync --extra api --extra rabbitmq --extra dev
uv run pytest
```

Review a local fixture through the CLI:

```bash
uv run contractmate review tests/fixtures/vendor-agreement.txt
```

Start PostgreSQL and RabbitMQ:

```bash
docker compose up -d postgres rabbitmq
```

RabbitMQ management is available at `http://localhost:15672` with the local
credentials defined in `docker-compose.yml`.

Create a local environment file from `.env.example`, then start the API:

```bash
cp .env.example .env
uv run uvicorn contractmate.app:create_app --factory --reload --port 8000
```

The service exposes:

- `GET /health` for process health
- `GET /ready` for dependency readiness
- `POST /email/inbound` for signed Resend `email.received` events
- `/api/*` for authenticated workspace operations
- `GET /agentos/control-plane/status` for protected runtime status

### Start the frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

The local workspace runs at `http://localhost:5173` and proxies `/api` to the
configured `API_ORIGIN`.

Run frontend verification with:

```bash
npm test
npm run build
```

### Run asynchronous processing locally

Set `CONTRACT_PROCESSING_MODE=rabbitmq` for the API and start a separate worker:

```bash
CONTRACT_PROCESSING_MODE=rabbitmq uv run contractmate worker
```

Production Compose runs three small, independent services: `contract-worker`
for review jobs, `knowledge-index-worker` for chat indexing, and
`delivery-worker` for durable outbound email and index-outbox delivery.

Long-running review and knowledge consumers disable AMQP heartbeats because
their synchronous OCR and model calls can exceed a heartbeat interval. Their
reconnect loops recover failed TCP connections when the next broker operation
runs. Short-lived publisher connections still use `RABBITMQ_HEARTBEAT_SECONDS`.
Failed jobs move through the TTL retry queue and reach the dead-letter queue
after `RABBITMQ_MAX_ATTEMPTS`.

## Configuration

Use `.env.example`, `frontend/.env.example`, and `worker.env.example` as the
source of truth for supported variables. The groups below describe the values
that define a production deployment.

### Frontend

```dotenv
API_ORIGIN=https://api.samvid.online
VITE_NEON_AUTH_URL=https://<neon-auth-host>/neondb/auth
MAX_FILE_SIZE_MB=20
```

`VITE_NEON_AUTH_URL` is a public service endpoint, not a secret.

### API

```dotenv
APP_ENV=production
APP_BASE_URL=https://api.samvid.online
FRONTEND_ORIGIN=https://samvid.online
ALLOWED_HOSTS=api.samvid.online,*.vercel.app

AUTH_MODE=neon
NEON_AUTH_URL=https://<neon-auth-host>/neondb/auth
NEON_AUTH_REQUIRE_EMAIL_VERIFIED=true
SAMVID_SUPER_ADMIN_EMAIL=<verified super-admin email>

DATABASE_URL=<pooled Neon PostgreSQL URL>
DATABASE_URL_UNPOOLED=<direct Neon PostgreSQL URL>
AUTO_INITIALIZE_DATABASE=false

DOCUMENT_STORAGE_BACKEND=vercel_blob
CONTRACT_PROCESSING_MODE=rabbitmq
RABBITMQ_URL=<CloudAMQP amqps URL>

# Start in observe mode, then enforce once dashboards show expected traffic.
UPSTASH_REDIS_REST_URL=https://<your-upstash-endpoint>
UPSTASH_REDIS_REST_TOKEN=<secret>
RATE_LIMIT_MODE=observe

OPENAI_API_KEY=<secret>
ENABLE_OCR=true
OCR_PROVIDER=sarvam
SARVAM_API_KEY=<secret>
SARVAM_OCR_MAX_CONCURRENCY=2

RESEND_INBOUND_ENABLED=true
RESEND_WEBHOOK_SECRET=<Resend signing secret>
RESEND_INBOUND_RECIPIENTS=contracts@inbound.samvid.online
RESEND_API_KEY=<secret>
EMAIL_FROM_ADDRESS=contracts@samvid.online
AUTO_SEND_REVIEW_EMAIL=true
```

Upstash is used only by the API for distributed admission control. It applies
per-account limits to chat, reads, mutations, review uploads, and inbound
email. Redis keys contain SHA-256 account or sender identifiers only; contract
content is never written to Redis. Use `observe` to measure limits without
blocking requests, then switch to `enforce` after verification.

Apply schema changes from a trusted environment using the direct Neon URL
before deploying the API:

```bash
DATABASE_URL_UNPOOLED='<direct Neon PostgreSQL URL>' \
SAMVID_SUPER_ADMIN_EMAIL='<verified super-admin email>' \
uv run contractmate migrate
```

The migration creates the account and access-audit tables and seeds the configured
super-admin. Delete the stale `email-workspace` test records and their Blob objects
before enabling private accounts in production. Keep
`AUTO_INITIALIZE_DATABASE=false` in Vercel so DDL is never performed during a
cold start.

### Worker

The worker shares the database, Blob, RabbitMQ, model, OCR, and outbound email
configuration with the API. It does not need Neon Auth variables,
`SAMVID_SUPER_ADMIN_EMAIL`,
`RESEND_WEBHOOK_SECRET`, or `RESEND_INBOUND_RECIPIENTS`.

Required worker-specific production values include:

```dotenv
APP_ENV=production
FRONTEND_ORIGIN=https://samvid.online
DATABASE_URL=<pooled Neon PostgreSQL URL>
AUTO_INITIALIZE_DATABASE=false
DOCUMENT_STORAGE_BACKEND=vercel_blob
BLOB_READ_WRITE_TOKEN=<long-lived private Blob token>
INBOUND_ATTACHMENT_DIR=/tmp/samvid/inbound-email
CONTRACT_PROCESSING_MODE=rabbitmq
RABBITMQ_URL=<CloudAMQP amqps URL>
OPENAI_API_KEY=<secret>
SARVAM_API_KEY=<secret>
SARVAM_OCR_MAX_CONCURRENCY=2
RESEND_API_KEY=<secret>
EMAIL_FROM_ADDRESS=contracts@samvid.online
AUTO_SEND_REVIEW_EMAIL=true
```

`INBOUND_ATTACHMENT_DIR` is temporary scratch space. Durable contract files
remain in private Blob storage and workflow state remains in Neon.

## Email Intake and Replies

Create a Resend webhook for the `email.received` event:

```text
https://api.samvid.online/email/inbound
```

Set the webhook signing secret as `RESEND_WEBHOOK_SECRET` on the API only. The
endpoint verifies `svix-id`, `svix-timestamp`, and `svix-signature` before it
parses the JSON payload.

For every accepted delivery, Samvid:

1. Confirms the recipient is in `RESEND_INBOUND_RECIPIENTS`.
2. Retrieves the complete message and attachment metadata from Resend.
3. Downloads up to five non-inline PDF, DOCX, or TXT attachments from Resend's
   signed HTTPS attachment URLs.
4. Rejects unsupported or oversized files without creating unsafe work.
5. Resolves the sender to a private account, creating an unclaimed account for a new sender.
6. Stores accepted files, creates account-scoped contract records, and publishes review jobs.
7. Preserves the sender, subject, Message-ID, and References for the worker.
8. Sends `Re: <original subject>` with a professional review, contract link,
   `In-Reply-To`, and `References` after processing completes.

Transient Resend, storage, database, and RabbitMQ failures return HTTP 500 so
Resend can retry. Permanent attachment rejections are acknowledged without
repeated delivery attempts.

When using a Resend test sender, outbound delivery is restricted to the email
address associated with that Resend account. Verify the Samvid sending domain
before enabling replies to customers.

## Authentication and Workspace Access

Samvid uses Neon Auth for browser sessions. The React client obtains a
short-lived Neon JWT and sends it as a Bearer token on workspace requests.
FastAPI validates the token and applies workspace authorization independently of
the frontend.

Configure the production Neon branch with:

- `https://samvid.online` as an exact trusted domain
- `http://localhost:5173` as a development trusted domain
- email/password sign-up and sign-in enabled
- verification at sign-up enabled with the verification-code method
- a custom SMTP provider for verification and password-recovery delivery
- the same Auth URL in `VITE_NEON_AUTH_URL` and `NEON_AUTH_URL`

Authentication emails are sent by Neon Auth's configured SMTP provider. They do
not use Samvid's inbound Resend webhook, API email adapter, or EC2 worker.

Each verified Neon identity is bound to one private Samvid account. Normal users
can access only contracts in their own internal workspace. The address in
`SAMVID_SUPER_ADMIN_EMAIL` receives a separate read-only oversight account and
has no personal contract workspace. Existing `email-workspace` records are test
data and are deleted rather than assigned to a production account.

Optional `NEON_AUTH_JWKS_URL`, `NEON_AUTH_ISSUER`, and
`NEON_AUTH_AUDIENCE` values override endpoint-derived defaults. Production and
preview branches must use their matching Auth URLs because each branch has its
own issuer and signing keys.

### Authentication verification

1. Create an account and confirm the six-digit verification code is
   delivered.
2. Verify the account, sign in, and confirm `GET /api/auth/me` returns HTTP 200.
3. Sign in as two normal users and confirm neither account can list or open the
   other account's contracts.
4. Request a password reset, complete it from the email, and sign in with the
   new password.
5. Sign in with `SAMVID_SUPER_ADMIN_EMAIL` and confirm the read-only admin view
   can inspect both accounts without exposing mutation controls.

## Production Delivery

### Web and API on Vercel

The frontend deployment uses `frontend/` as its root directory. Routing
middleware keeps the React shell public for authentication screens and proxies
`/api` to `API_ORIGIN`; FastAPI remains the data-security boundary.

The backend deployment uses the repository root. `Dockerfile.vercel` packages
FastAPI as an OCI function that listens on Vercel's `PORT`. Both deployments
connect to the same private Blob store, while Neon provides PostgreSQL.

Recommended branded domains:

| Service | Domain |
| --- | --- |
| Samvid workspace | `https://samvid.online` |
| Samvid API | `https://api.samvid.online` |
| Contract inbox | `contracts@inbound.samvid.online` |
| Authentication sender | `auth@samvid.online` |

Vercel deployment aliases can remain available for diagnostics, but production
environment variables and provider redirects should use the branded domains.

Deploy the backend manually from the repository root when the Vercel deployment
is not connected to GitHub:

```bash
vercel --prod
```

### Worker on EC2

GitHub Actions tests the backend and frontend, builds both production images,
and publishes the worker as:

```text
ghcr.io/piyusharyan/samvid-contract-worker:latest
ghcr.io/piyusharyan/samvid-contract-worker:<git-commit-sha>
```

The EC2 host pulls the prebuilt image; it does not build application images.
Authenticate to GHCR once with a classic GitHub token limited to
`read:packages`, then deploy from the Compose definition:

```bash
cd ~/samvid-worker
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d --no-build --force-recreate
docker compose -f docker-compose.worker.yml ps
docker compose -f docker-compose.worker.yml logs --tail=100 contract-worker
docker compose -f docker-compose.worker.yml logs --tail=100 delivery-worker
```

Pin an immutable release when reproducibility is required:

```bash
export WORKER_IMAGE=ghcr.io/piyusharyan/samvid-contract-worker:<git-commit-sha>
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d --no-build --force-recreate
```

The Compose service has no public port, restarts unless stopped, limits resource
usage, and rotates Docker logs. The EC2 security group needs no application
inbound rule. Restrict SSH to administrator addresses and retain outbound access
to Neon, CloudAMQP, Vercel Blob, OpenAI, Sarvam, and Resend.

### Release order

1. Run backend and frontend tests locally.
2. Push the release and wait for CI to publish the GHCR worker image.
3. Deploy the Vercel API and frontend configuration.
4. Pull and recreate the EC2 worker.
5. Confirm `/health` and `/ready` return success.
6. Send a small supported contract to the production inbox.
7. Confirm the job reaches CloudAMQP and the worker completes it.
8. Confirm the review is visible in Samvid and the threaded reply is delivered.

## Operational Checks

Inspect worker state:

```bash
docker compose -f docker-compose.worker.yml ps
docker inspect "$(docker compose -f docker-compose.worker.yml ps -q contract-worker)" \
  --format 'status={{.State.Status}} restarts={{.RestartCount}}'
```

Follow worker logs:

```bash
docker compose -f docker-compose.worker.yml logs -f --tail=200 contract-worker
docker compose -f docker-compose.worker.yml logs -f --tail=200 delivery-worker
```

Validate production images locally:

```bash
docker build -f Dockerfile.vercel -t samvid-api:local .
docker build -f Dockerfile.worker -t samvid-worker:local .
```

`APP_ENV=production` fails fast when required credentials, PostgreSQL, private
document storage, RabbitMQ, or writable scratch storage are missing. Treat that
validation as a deployment guard, not an error to bypass.

## Product Boundary

Samvid turns contracts into structured, traceable work. It helps teams review,
coordinate, and follow through; final legal judgment, negotiation authority, and
contract execution remain with the people responsible for the agreement.
