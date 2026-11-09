# syntax=docker/dockerfile:1
# Build from the repo root: docker build -f apps/web/Dockerfile .

# --- build stage: Node is only needed to compile; it never ships ---
FROM node:20.19-alpine AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

# --- runtime stage: nginx serves static files and reverse-proxies the API (same origin, no CORS) ---
FROM nginx:1.28-alpine
# The official image runs envsubst over /etc/nginx/templates/*.template at startup, substituting
# only variables that are set in the environment (so nginx's own $host etc. are left alone).
ENV API_UPSTREAM=http://api:8000
COPY deploy/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
