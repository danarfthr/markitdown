# frontend

Next.js UI for the MarkItDown converter. See the [root README](../README.md) for
setup, commands, and how this half connects to the Python service.

The short version: this app is **not standalone**. It calls `/api/convert`, which
Vercel routes to `../backend` in production and `next.config.ts` proxies to
`127.0.0.1:8000` in development. Start the backend first.

Package manager is **pnpm** — do not add `package-lock.json` or `yarn.lock`.
