# Chat Operations

Samvid's contract chat uses PostgreSQL with `pgvector`, embedding and reranking
through Vercel AI Gateway, and a dedicated RabbitMQ knowledge-index worker. The normal
`contract-worker` continues to review contracts. Do not replace it with the
knowledge-index worker: both services must run.

## Required configuration

Set the following values for the API deployment and the EC2 worker's
`.env.worker` file. The worker file is read by both Compose services.

```dotenv
DATABASE_URL=postgresql://...
CONTRACT_PROCESSING_MODE=rabbitmq
RABBITMQ_URL=amqps://...

AGENTIC_CHAT_ENABLED=false
CHAT_MODEL_ID=gpt-5-mini

AI_GATEWAY_API_KEY=...
AI_GATEWAY_BASE_URL=https://ai-gateway.vercel.sh/v1
EMBEDDING_MODEL_ID=openai/text-embedding-3-small
EMBEDDING_DIMENSIONS=1024
RERANK_MODEL_ID=cohere/rerank-v3.5

RABBITMQ_KNOWLEDGE_INDEX_QUEUE=contract.knowledge-index.q
RABBITMQ_KNOWLEDGE_INDEX_RETRY_QUEUE=contract.knowledge-index.retry.q
RABBITMQ_KNOWLEDGE_INDEX_DLQ=contract.knowledge-index.dlq
```

The normal review-worker variables remain required, including document storage,
`OPENAI_API_KEY`, and OCR credentials where OCR is enabled. Set
`AGENTIC_CHAT_ENABLED=false` for Phase 1; it reserves the flag for the later
multi-agent workflow.

`DATABASE_URL` must point to PostgreSQL. SQLite cannot support pgvector or the
production chat index. Run the deployed schema migration before deployment, and
verify the database contains the `vector` extension and the chat/knowledge-index
tables.

The API also needs `AI_GATEWAY_API_KEY` and the same model settings. The API
performs retrieval and response generation; the
`knowledge-index-worker` performs chunk embedding and index maintenance.

## Deploy or update the workers

On the EC2 instance, update the image and recreate both services:

```bash
cd ~/samvid-worker
docker compose -f docker-compose.worker.yml pull
docker compose -f docker-compose.worker.yml up -d --remove-orphans
docker compose -f docker-compose.worker.yml ps
```

Expected services:

- `contract-worker`: consumes `contract.review.q` and completes review jobs.
- `knowledge-index-worker`: consumes `contract.knowledge-index.q` and writes
  pgvector knowledge chunks after a review is available.
- `delivery-worker`: publishes durable knowledge-index outbox intents to
  RabbitMQ.

Do not run more than one instance of either service unless RabbitMQ throughput,
database capacity, and provider rate limits have been assessed. RabbitMQ gives
each message to one consumer, so replicas are safe only when the index worker is
idempotent.

## Operational checks

Check process health and the deployed image revision:

```bash
docker compose -f docker-compose.worker.yml ps
docker compose -f docker-compose.worker.yml logs --tail=200 contract-worker
docker compose -f docker-compose.worker.yml logs --tail=200 knowledge-index-worker
docker inspect "$(docker compose -f docker-compose.worker.yml ps -q knowledge-index-worker)" \
  --format 'status={{.State.Status}} restarts={{.RestartCount}} revision={{index .Config.Labels "org.opencontainers.image.revision"}}'
```

For an end-to-end smoke test, upload or email a supported contract, wait for the
review to reach `review_ready`, then confirm that the knowledge-index worker
consumes its job without retries or dead-lettering. Open the contract chat and
ask a question that is answered by a specific clause. The answer should include
citations to the relevant contract pages or sections.

If index jobs accumulate, inspect the RabbitMQ queues in CloudAMQP:

- `contract.knowledge-index.q`: work waiting to be indexed.
- `contract.knowledge-index.retry.q`: delayed transient failures.
- `contract.knowledge-index.dlq`: failures that exhausted the configured retry
  limit and require investigation or replay.

Typical causes are an expired AI Gateway key, an embedding-dimension mismatch
between the configured value and the pgvector column, a missing `vector`
extension, PostgreSQL connectivity failures, or upstream provider rate limiting.

## Recover a failed index

Scoped chat deliberately returns `contract_index_not_ready` while a selected
contract is pending or indexing, and `contract_index_failed` after all three
worker attempts fail. It does not fall back to another contract or to review
JSON.

First inspect both durable failure records for the affected contract:

```sql
SELECT id, contract_id, contract_version_id, status, chunk_count, error_message, updated_at
FROM knowledge_indexes
WHERE contract_id = '<contract-id>'
ORDER BY updated_at DESC;

SELECT id, contract_id, contract_version_id, status, attempts, last_error, updated_at
FROM knowledge_index_outbox
WHERE contract_id = '<contract-id>'
ORDER BY updated_at DESC;
```

After correcting the reported provider, database, or configuration problem,
queue only that contract for an operator retry:

```bash
contractmate knowledge-retry-failed --contract-id <contract-id>
```

Omit `--contract-id` only when every failed index should be retried. Wait for
the index to become `ready`, then verify `chunk_count > 0` and that matching
rows exist in `knowledge_chunks`. Only after that verification should an
operator remove stale messages for the same contract/version from
`contract.knowledge-index.dlq`; leave unrelated DLQ messages intact.

Deploy the API, contract worker, knowledge-index worker, and delivery worker
from images bearing the same immutable source revision so the outbox envelope
and consumer lifecycle remain compatible.

## Rollback

To temporarily stop indexing while preserving existing chat data, stop only
`knowledge-index-worker`:

```bash
docker compose -f docker-compose.worker.yml stop knowledge-index-worker
```

Keep `contract-worker` running. Contract intake, OCR, review, signing, and email
delivery do not depend on the chat worker.
