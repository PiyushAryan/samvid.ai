# Frontend Architecture

`src/app` owns Next.js routes, layouts, metadata, and route handlers. Route pages stay thin: they compose a feature entrypoint and keep server-only route concerns local.

`src/features` owns product behavior. Each feature owns its pages, hooks, APIs, types, and tests. Cross-feature reuse must happen through a focused component or helper export, never by importing another feature's route page or shell.

`src/components/ui` contains reusable UI primitives. `src/components/shared` contains presentational patterns used across product features. Neither directory may import feature code.

`src/lib` contains framework and platform adapters: authenticated HTTP handling, navigation compatibility, favicon/theme helpers, and small generic utilities. It must not import feature UI.

`src/styles/globals.css` is limited to application-wide variables, fonts, resets, and workspace-wide primitives. Marketing and account styles are loaded by their route-group layouts. New feature-specific styles should be colocated with the feature.

`src/test` contains only global test setup and mocks. Product tests are colocated with the feature they cover.

Run `npm run check:boundaries` before submitting a frontend refactor.
