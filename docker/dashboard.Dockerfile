# syntax=docker/dockerfile:1
# Multi-stage build for the Next.js dashboard (dashboard/).
# Build context MUST be the dashboard/ directory, e.g.:
#   docker build -f docker/dashboard.Dockerfile dashboard
# (docker-compose.yml sets context: ../dashboard / dockerfile: ../docker/dashboard.Dockerfile)

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json ./
# Prefer a reproducible install when a lockfile exists; fall back to a
# regular install otherwise (the dashboard may not have a lockfile yet
# while it's still being scaffolded in parallel).
COPY package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Build-time env the Next.js build may inline into client bundles.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build

FROM node:20-alpine AS runtime
RUN addgroup --system swasthya && adduser --system --ingroup swasthya swasthya

WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.ts ./next.config.ts

RUN chown -R swasthya:swasthya /app
USER swasthya

EXPOSE 3000
CMD ["npm", "start"]
