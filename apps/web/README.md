# Web Frontend

Next.js frontend for the RAG assistant.

## Local run

```powershell
npm install
npm run dev
```

The app runs on `http://127.0.0.1:3000` and proxies API requests to the Python backend configured by `BACKEND_URL`.

## Folder role

- `src/app`: Next.js App Router pages and styles.
- `public`: frontend-only static assets.
- `next.config.ts`: API/static proxy rules to the Python backend during migration.
