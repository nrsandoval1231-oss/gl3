# Web application

Responsive React + TypeScript application. Backend response schemas generate `src/api/generated.ts`; refresh them with `npm run generate:api` after exporting the FastAPI OpenAPI contract. The Vite development server proxies `/api` to `127.0.0.1:8000`. Use `npm ci`, `npm run typecheck`, and `npm run build` from this directory. Playwright regression tests run with `npm test`; live acceptance tests require a local authenticated account and retained source data.
