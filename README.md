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
uv sync --extra api --extra dev
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

The review path uses Agno with OpenAIChat. Set `OPENAI_API_KEY` in `.env`.
Scanned PDFs use Sarvam Vision before review. Set `SARVAM_API_KEY`, and choose
the document's primary BCP-47 language with `SARVAM_OCR_LANGUAGE` (English is
`en-IN`). PDFs over Sarvam's 10-page per-job limit are split and reassembled
automatically. Partial OCR jobs fail visibly and are never sent to the reviewer.

Inbound email processing is autonomous by default: a received email attachment
is reviewed and a response email is sent or dry-run printed. Binding legal
actions such as signing, accepting terms or sending negotiation commitments
still require an explicit approval workflow.
