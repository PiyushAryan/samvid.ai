# Frontend Architecture

`src/app` owns Next.js routes, layouts, metadata, and route handlers. Route pages stay thin: they compose a feature entrypoint and keep server-only route concerns local.

`src/features` owns product behavior. Each feature owns its pages, components, APIs, types, styles, and tests. Cross-feature reuse happens through focused component or type imports, never by importing another feature's route page or shell.

`src/components/ui` contains reusable UI primitives. `src/components/shared` contains presentational patterns used across product features. Neither directory may import feature code.

`src/lib` contains framework and platform adapters: auth-session access, authenticated HTTP primitives, navigation compatibility, favicon/theme helpers, and small generic utilities. It never imports a feature.

`src/styles/globals.css` is limited to application-wide variables, fonts, resets, and portalled browser surfaces. Feature styles are colocated CSS Modules and are loaded only by the route groups or components that use them.

`src/test` contains only global test setup and mocks. Product tests are colocated with the feature they cover.

Feature ownership is direct:

- `auth` owns account policy and screens; `lib/auth-session.ts` owns the low-level Neon session adapter.
- `contracts`, `signing`, and `chat` own their endpoints, schemas, pages, and regression tests.
- `workspace` owns only the authenticated shell and navigation.
- `admin`, `settings`, and `marketing` own their route implementations and styles.

Run `npm run check:boundaries` before submitting a frontend refactor. It parses TypeScript imports, rejects forbidden dependency directions and legacy monoliths, and verifies that every public asset has a runtime or metadata reference.
