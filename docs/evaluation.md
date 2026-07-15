# ContractMate Evaluation

Initial release gates:

- Every displayed risk has exact evidence on an existing page.
- Agno/OpenAI-generated findings with unsupported evidence are removed before display.
- Duplicate uploads and duplicate inbound email events do not create duplicate reviews.
- Prompt-injection documents cannot override system instructions or trigger tools.
- Scanned PDFs are reviewed only after every Sarvam Vision OCR chunk completes successfully.
- OCR failures and partial OCR results fail visibly instead of producing incomplete analysis.
- Approval records are immutable once a decision is made.
- Production Control Plane status rejects unauthenticated requests.
- RabbitMQ job messages do not include full contract text.
