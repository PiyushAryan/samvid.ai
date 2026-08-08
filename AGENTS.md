# Repository Guidelines

## Project Structure & Module Organization

The Python backend lives in `src/contractmate/`. Keep HTTP endpoints in `api/`, persistence code in `db/`, business logic in `services/`, external integrations in focused packages such as `email/`, `slack/`, and `ocr/`, and background consumers in `workers/`. Backend tests are under `tests/unit/` and `tests/e2e/`; reusable samples belong in `tests/fixtures/`.

The Next.js frontend is in `frontend/`. App Router pages and layouts live in `frontend/src/app/`, shared React code in `frontend/src/components/`, and static images in `frontend/public/`. Deployment definitions are in `Dockerfile*`, `docker-compose*.yml`, `infrastructure/`, and `.github/workflows/`.

## Build, Test, and Development Commands

- `uv sync --extra api --extra rabbitmq --extra dev`: install backend and development dependencies.
- `uv run pytest`: run all Python tests; pass a path such as `tests/unit/test_review_service.py` for a focused run.
- `docker compose up -d postgres rabbitmq`: start local infrastructure.
- `uv run uvicorn contractmate.app:create_app --factory --reload --port 8000`: run the API locally.
- `cd frontend && npm ci`: install the locked frontend dependency set.
- `cd frontend && npm run dev`: start Next.js at `http://localhost:3000`.
- `cd frontend && npm test -- --run`: run Vitest once; `npm test` starts watch mode.
- `cd frontend && npm run build`: type-check and create the production build.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, `snake_case` functions/modules, and `PascalCase` classes in Python. TypeScript uses strict mode, two-space indentation, semicolons, `camelCase` functions, and `kebab-case` component/type filenames. Follow nearby code because no repository-wide formatter is configured.

## Testing Guidelines

Pytest discovers `test_*.py` files; Vitest uses colocated `*.test.ts` and `*.test.tsx` files. Add regression tests for behavior changes; mock external boundaries in unit tests. No coverage threshold is configured, but CI requires backend tests, frontend tests, and the frontend build to pass.

## Commit & Pull Request Guidelines

Use Conventional Commits: `fix:` for patches, `feat:` for features, and types such as `build:`, `chore:`, `ci:`, `docs:`, `style:`, `refactor:`, `perf:`, or `test:`. Add an optional scope, e.g. `feat(parser): support arrays`. Mark incompatible changes with `type!:` and/or a `BREAKING CHANGE: description` footer. Other footers should use git-trailer style. Keep commits focused. Pull requests must explain problem and solution, link issues, note configuration or migration effects, include screenshots for UI changes, and pass CI-equivalent checks.

## Security & Configuration

Copy values from `.env.example`, `frontend/.env.example`, or `worker.env.example`; never commit populated environment files or credentials. Preserve authenticated document access, webhook verification, account scoping, and file-validation checks when changing intake or storage flows.
