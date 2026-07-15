# ContractMate Architecture

The implementation follows `contractmate_mvp_architecture.md`.

Local development uses:

- PostgreSQL for durable MVP state.
- Local filesystem storage behind the same storage boundary intended for S3.
- RabbitMQ through Docker Compose for durable queue topology testing.
- A `PdfMuseDocumentParser` wrapper with a deterministic fallback when pdfmuse is not installed.
- A Sarvam Vision OCR adapter for scanned PDFs, with automatic 10-page chunking and normalized page-aware output.
- Agno-backed structured contract extraction using OpenAIChat through the same typed review interface.
- A Control Plane status endpoint that exposes runtime metadata without exposing contract text.

The domain layer is channel-independent. Email, S3, RabbitMQ/Amazon MQ, Postgres, pdfmuse, Sarvam Vision, Agno and AgentOS Control Plane integrations are isolated behind adapters so production services can replace local implementations without rewriting contract review logic.
