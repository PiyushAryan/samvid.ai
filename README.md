ContractMate
============

ContractMate is an email-native MVP for reviewing emailed contracts with typed
schemas, deterministic document parsing, evidence validation, durable workflow
state, and human-approved response drafts.

Quick start
-----------

```bash
uv sync --extra dev
uv run pytest
uv run contractmate review tests/fixtures/vendor-agreement.txt
```

Run the HTTP app for inbound email webhooks:

```bash
uv sync --extra api --extra rabbitmq --extra dev
uv run uvicorn contractmate.app:create_app --factory --reload --port 8000
```

Example local inbound email payload:

```json
{
  "message_id": "email-1",
  "thread_id": "thread-1",
  "from_address": "sender@example.com",
  "to_addresses": ["contracts@example.com"],
  "subject": "Please review this agreement",
  "text": "Can you review the attached contract?",
  "attachments": [
    {
      "filename": "vendor-agreement.txt",
      "mime_type": "text/plain",
      "local_path": "tests/fixtures/vendor-agreement.txt"
    }
  ]
}
```

Local development defaults to PostgreSQL and filesystem storage under
`.contractmate/`. Production integrations are isolated behind adapters for
Email, S3, RabbitMQ/Amazon MQ, PostgreSQL, pdfmuse, Agno and the AgentOS
Control Plane.

Implemented MVP slice
---------------------

- Pydantic schemas for parsed documents, contract reviews, risks, evidence and approvals.
- File validation with MIME sniffing, size limits and SHA-256 hashing.
- Parser abstraction with a pdfmuse-facing wrapper and deterministic local fallback.
- Sarvam Vision OCR for scanned PDFs, including automatic 10-page job chunking and page-number restoration.
- Contract review service with evidence-grounded risk extraction.
- Agno-backed structured extraction using OpenAIChat and typed output validation.
- Evidence validator that removes unsupported risk findings.
- Workflow state machine and durable local repository matching the planned entities.
- Inbound email webhook parsing and SMTP/dry-run response delivery.
- Human approval records that permit one final decision per proposed action.
- RabbitMQ job message contract and topology adapter for durable async processing.
- Control Plane runtime status endpoint protected by `OS_SECURITY_KEY` or JWT.
- FastAPI app factory with `/health`, `/ready`, Control Plane status and email inbound webhook handling.

Configuration
-------------

Copy `.env.example` and fill in real values for deployed environments. Never
commit secrets.

```dotenv
DATABASE_URL=postgresql://contractmate:contractmate@localhost:5432/contractmate
LOCAL_STORAGE_DIR=.contractmate/files
RABBITMQ_URL=amqp://contractmate:contractmate@localhost:5672/%2F
CONTRACT_PROCESSING_MODE=sync
MODEL_PROVIDER=openai
MODEL_ID=gpt-5-mini
OPENAI_API_KEY=
ENABLE_OCR=true
OCR_PROVIDER=sarvam
SARVAM_API_KEY=
SARVAM_OCR_LANGUAGE=en-IN
SARVAM_OCR_TIMEOUT_SECONDS=600
AUTO_SEND_REVIEW_EMAIL=true
EMAIL_FROM_ADDRESS=onboarding@resend.dev
RESEND_API_KEY=re_xxxxxxxxx
OS_SECURITY_KEY=
JWT_VERIFICATION_KEY=
```

Replace `re_xxxxxxxxx` with your real Resend API key. During initial testing,
`onboarding@resend.dev` can send only to the email address associated with your
Resend account. Verify a domain and update `EMAIL_FROM_ADDRESS` before sending
to other recipients.

Send a configuration test:

```bash
uv run contractmate send-test-email --to piyusharyan81@gmail.com
```

Local RabbitMQ and PostgreSQL are available through Docker Compose:

```bash
docker compose up -d postgres rabbitmq
```

RabbitMQ management UI runs on `http://localhost:15672` with the local
development credentials in `docker-compose.yml`.

Asynchronous contract review
----------------------------

RabbitMQ processing is opt-in. Start PostgreSQL and RabbitMQ, switch the API to
queue mode, and run the persistent consumer in a separate process:

```bash
docker compose up -d postgres rabbitmq
CONTRACT_PROCESSING_MODE=rabbitmq uv run contractmate worker
```

With `CONTRACT_PROCESSING_MODE=rabbitmq`, browser uploads and inbound email
attachments are validated and stored before a durable identifier-only job is
published. The worker downloads that exact stored version, verifies its SHA-256,
runs parsing, OCR and Agno review, persists the result, and acknowledges the job.
Failures are retried through the TTL retry queue and move to the DLQ after
`RABBITMQ_MAX_ATTEMPTS`. `RABBITMQ_HEARTBEAT_SECONDS` should exceed the longest
expected OCR/model call. Email reviews are sent by the worker after completion.

The API and worker must share `DATABASE_URL`, document-storage credentials,
OpenAI/Sarvam/Resend settings, and RabbitMQ topology settings. Vercel Functions
must not be used as the persistent consumer; deploy the worker on a service that
runs long-lived processes. Keep `CONTRACT_PROCESSING_MODE=sync` until both the
managed RabbitMQ broker and worker deployment are healthy.

The review path uses Agno with OpenAIChat. Set `OPENAI_API_KEY` in `.env`.
Scanned PDFs use Sarvam Vision before review. Set `SARVAM_API_KEY`, and choose
the document's primary BCP-47 language with `SARVAM_OCR_LANGUAGE` (English is
`en-IN`). PDFs over Sarvam's 10-page per-job limit are split and reassembled
automatically. Partial OCR jobs fail visibly and are never sent to the reviewer.

Inbound email processing is autonomous by default: a received email attachment
is reviewed and a response email is sent or dry-run printed. Binding legal
actions such as signing, accepting terms or sending negotiation commitments
still require an explicit approval workflow.

Production deployment
---------------------

Production uses two Vercel projects from this repository:

- The frontend project has `frontend/` as its Root Directory. Routing Middleware
  keeps the landing page public, protects `/contracts`, and proxies `/api` to the
  backend through `API_ORIGIN`.
- The backend project uses the repository root. `Dockerfile.vercel` packages the
  FastAPI service as an OCI function that listens on Vercel's `PORT`.
- A private Vercel Blob store is connected to both projects. Browser uploads go
  directly to Blob, so contracts up to `MAX_FILE_SIZE_MB` do not pass through
  Vercel's Function request-body limit.
- PostgreSQL must be supplied through `DATABASE_URL`; Neon or Supabase can be
  connected through the Vercel Marketplace.

Set these frontend project variables:

```text
API_ORIGIN=https://your-backend-project.vercel.app
APP_ACCESS_USERNAME=samvid
APP_ACCESS_PASSWORD=<same strong password as the backend>
MAX_FILE_SIZE_MB=20
```

Set these backend project variables, marking credentials as secrets:

```text
APP_ENV=production
ALLOWED_HOSTS=*.vercel.app,api.samvid.ai
APP_ACCESS_USERNAME=samvid
APP_ACCESS_PASSWORD=<strong shared password>
APP_BASE_URL=https://your-backend-project.vercel.app
DATABASE_URL=<managed PostgreSQL connection string>
DATABASE_URL_UNPOOLED=<direct Neon connection string>
AUTO_INITIALIZE_DATABASE=false
CONTRACT_PROCESSING_MODE=sync
DOCUMENT_STORAGE_BACKEND=vercel_blob
INBOUND_ATTACHMENT_DIR=/tmp/samvid/inbound-email
INBOUND_EMAIL_SECRET=<strong webhook secret>
OPENAI_API_KEY=<secret>
ENABLE_OCR=true
SARVAM_API_KEY=<secret>
SARVAM_OCR_TIMEOUT_SECONDS=240
AUTO_SEND_REVIEW_EMAIL=true
EMAIL_FROM_ADDRESS=contracts@your-domain.example
RESEND_API_KEY=<secret>
MAX_FILE_SIZE_MB=20
```

Connect the same private Blob store to each project so Vercel injects
`BLOB_STORE_ID` and its short-lived OIDC credential. For a backend hosted outside
Vercel, use `BLOB_READ_WRITE_TOKEN` instead.

Initialize the production schema once with `AUTO_INITIALIZE_DATABASE=true`, then
set it to `false` for the deployed service. This keeps schema DDL out of Vercel
container cold starts.

Run the persistent RabbitMQ consumer on an EC2 instance with Docker. The worker
does not accept inbound traffic and does not need a public port or persistent
volume; contract files remain in Vercel Blob and workflow state remains in Neon.
On the EC2 host:

```bash
git clone <repository-url> samvid
cd samvid
cp worker.env.example .env.worker
# Fill .env.worker with production secrets, then restrict it.
chmod 600 .env.worker
docker compose -f docker-compose.worker.yml config
docker compose -f docker-compose.worker.yml up -d --build
docker compose -f docker-compose.worker.yml ps
docker compose -f docker-compose.worker.yml logs -f --tail=100
```

The production worker is sized for a 2 vCPU, 2 GiB `t3.small`. The container is
limited to 1.5 CPUs and 1.5 GiB RAM, leaving capacity for the host OS and Docker.
Configure 2 GiB of swap to protect image builds from transient memory pressure,
and monitor runtime usage with `docker stats`. Docker logs rotate at 10 MiB. The
security group needs no application inbound rule; restrict SSH to an
administrator IP and retain outbound access to Neon PostgreSQL, CloudAMQP over
TLS, Vercel Blob, OpenAI, Sarvam, and Resend.

Keep the Vercel API on `CONTRACT_PROCESSING_MODE=sync` until the worker log says
it is polling `contract.review.q`. Then configure the same `RABBITMQ_URL` and
queue names on Vercel, set `CONTRACT_PROCESSING_MODE=rabbitmq`, redeploy the API,
and submit a small test contract. Roll back by returning the Vercel setting to
`sync`.

Local production-image validation:

```bash
docker build -t samvid:local .
docker run --rm -p 8000:8000 --env-file .env samvid:local
```

`APP_ENV=production` intentionally fails fast when required secrets, PostgreSQL,
private document storage, or writable scratch storage are missing.
