# stage1: build
FROM node:20-alpine AS builder
WORKDIR /build
ARG VITE_WS_BASE=
ENV VITE_WS_BASE=${VITE_WS_BASE}
RUN corepack enable && corepack prepare pnpm@10 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# stage2: nginx serve
FROM nginx:alpine
ARG APP_REVISION=development
LABEL org.opencontainers.image.revision=$APP_REVISION
COPY --from=builder /build/dist /usr/share/nginx/html
RUN printf '{"revision":"%s"}\n' "$APP_REVISION" > /usr/share/nginx/html/version.json
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
