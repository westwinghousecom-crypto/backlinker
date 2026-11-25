# QuickIndex Frontend

Next.js (App Router) + Tailwind + shadcn/ui frontend for bulk backlink indexing.

## Setup

```bash
cp .env.example .env.local   # set NEXT_PUBLIC_API_URL
npm install
npm run dev                  # http://localhost:3000 -> /dashboard
```

## Structure

- `src/app` - routes (thin pages)
- `src/features/submission` - form component, hook, API client, URL parser, types
- `src/components/ui` - shadcn components
- `src/lib/config.ts` - API base URL and placeholder `DEMO_USER_ID`

Submits `POST {API_URL}/api/v1/submit` with `{ user_id, urls }` (max 1,000 URLs).
