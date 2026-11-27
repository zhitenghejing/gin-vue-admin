# 如果需要用 cicd ，请设置环境变量：
# variables:
#     DOCKER_BUILDKIT: 1

FROM node:24.22.0-slim AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable && corepack prepare pnpm@10.34.8 --activate
COPY . /app
WORKDIR /app
RUN pnpm --version


FROM base AS build
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile --prod=false && pnpm run build


FROM nginx:alpine
LABEL MAINTAINER="bypanghu@163.com"
COPY --from=base  /app/.docker-compose/nginx/conf.d/my.conf /etc/nginx/conf.d/my.conf
COPY --from=build  /app/dist /usr/share/nginx/html
RUN ls -al /usr/share/nginx/html
