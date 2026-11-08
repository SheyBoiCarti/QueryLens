# Multi-stage build for React frontend
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json

RUN npm ci

COPY apps/web ./apps/web
RUN npm run build --workspace=apps/web

FROM caddy:2.7-alpine AS runner
COPY --from=builder /app/apps/web/dist /srv/web
COPY infra/proxy/Caddyfile /etc/caddy/Caddyfile
EXPOSE 443
