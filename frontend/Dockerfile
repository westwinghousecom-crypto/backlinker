# syntax=docker/dockerfile:1
#
# QuickIndex web app (Next.js 16, standalone output). Build context: ./frontend
#
#   docker build -t quickindex-web \
#     --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
#     --build-arg NEXT_PUBLIC_APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1 \
#     --build-arg NEXT_PUBLIC_APPWRITE_PROJECT_ID=your_project_id \
#     ./frontend
#
# IMPORTANT: Next.js INLINES every NEXT_PUBLIC_* value into the browser bundle at BUILD time. Setting them only when the
# container starts has no effect. They are therefore build ARGs, exported as ENV before `npm run build`, and a different
# API address or Appwrite project means a rebuild. They are public by design: put NO secrets in them.
# glibc (Debian) base, not Alpine: the Tailwind/LightningCSS/SWC native binaries are published for linux-gnu.

# ---------------------------------------------------------------------------------------------- deps
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------------------------------------- build
FROM node:22-bookworm-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_APPWRITE_ENDPOINT
ARG NEXT_PUBLIC_APPWRITE_PROJECT_ID
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_APPWRITE_ENDPOINT=${NEXT_PUBLIC_APPWRITE_ENDPOINT} \
    NEXT_PUBLIC_APPWRITE_PROJECT_ID=${NEXT_PUBLIC_APPWRITE_PROJECT_ID} \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# next.config.ts sets output: "standalone", which writes .next/standalone (server.js + only the node_modules it needs).
RUN npm run build

# ---------------------------------------------------------------------------------------------- runtime
# Production image: no npm, no devDependencies, no source. Only the traced standalone server, static assets and public/.
FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN groupadd --system --gid 10001 nextjs \
 && useradd --system --uid 10001 --gid nextjs --no-create-home --shell /usr/sbin/nologin nextjs

COPY --from=build --chown=nextjs:nextjs /app/public ./public
COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# /login is a prerendered page, so it answers 200 without any backend being reachable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["node", "server.js"]
