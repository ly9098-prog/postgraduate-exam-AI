# Stage 1: Install dependencies
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts=false

# Stage 2: Build
FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
# 3.6 GB production server (2026-08-06 迁移后): 提高堆上限，减少构建 OOM/GC 压力
ENV NODE_OPTIONS="--max-old-space-size=2048"
ARG NEXT_PUBLIC_ADMIN_API_BASE_URL=/api/admin/v1
ENV NEXT_PUBLIC_ADMIN_API_BASE_URL=${NEXT_PUBLIC_ADMIN_API_BASE_URL}
RUN npm run build

# Stage 3: Production runtime
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built assets
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
# Next.js 16 Turbopack standalone 偶发缺失 SSR chunk（如 _not-found 引用），仅合并 chunks 目录兜底（不覆盖路由清单）
COPY --from=builder --chown=nextjs:nodejs /app/.next/server/chunks ./.next/server/chunks

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
