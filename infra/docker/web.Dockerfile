# Multi-stage build for React frontend
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json

RUN npm ci

COPY apps/web ./apps/web
RUN npm run build --workspace=apps/web

FROM nginx:1.27-alpine AS runner

# Create non-root nginx user or use standard alpine nginx
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD wget --spider http://127.0.0.1:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
