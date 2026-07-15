# ContractMate Threat Model

- Uploaded contracts are untrusted input and may contain prompt-injection text.
- Inbound email webhooks must be verified with the shared secret in deployed environments.
- Sensitive external actions require persisted human approval.
- Agno/OpenAI may analyze and draft autonomously, but the app must not sign, accept terms or send binding legal commitments without approval.
- Contract text must not be written to general operational logs.
- RabbitMQ messages carry identifiers and routing metadata only, never full contract text.
- Production Control Plane access must require JWT or a scoped security mechanism.
- Local development stores files under `.contractmate/files`; production should use private encrypted S3.
