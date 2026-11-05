# ---- 前端构建 ----
FROM node:20-slim AS web
WORKDIR /src
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# ---- 后端构建 ----
# 发行版必须和运行阶段钉死在同一个：rust:1-slim 会跟着上游滚（现已是 trixie/glibc 2.41），
# 编出的二进制便要求 GLIBC_2.38，而 bookworm 只有 2.36——镜像构建照样成功，
# 容器一启动就 "version `GLIBC_2.38' not found"。
FROM rust:1-slim-bookworm AS build
# Limit concurrent rustc processes on resource-constrained development hosts.
# Override via SOORIN_BUILD_JOBS in the isolated Compose file.
ARG CARGO_BUILD_JOBS=1
WORKDIR /src
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config && rm -rf /var/lib/apt/lists/*
COPY Cargo.toml Cargo.lock ./
COPY crates/ crates/
COPY migrations/ migrations/
COPY soorin/ontology/soc_ontology_v1.yaml soorin/ontology/soc_ontology_v1.yaml
# docs_corpus.rs 用 include_str! 把产品内文档编进二进制，所以它是后端的源码依赖，
# 不只是前端资源——漏掉这行，cargo build 直接报 couldn't read。
COPY web/src/docs/ web/src/docs/
# utopia-store::palette compiles the UI palette into backend validation tests
# and runtime helpers; copying only the documentation leaves this include out.
COPY web/src/palette.ts web/src/palette.ts
# RUN cargo build --release -p utopia-server
# More tolerant Cargo networking for slow or unstable connections.
ENV CARGO_HTTP_TIMEOUT=180 \
    CARGO_HTTP_LOW_SPEED_LIMIT=1 \
    CARGO_NET_RETRY=6 \
    CARGO_HTTP_MULTIPLEXING=false

# Preserve downloaded Rust dependencies between failed/retried builds.
RUN --mount=type=cache,target=/usr/local/cargo/registry,sharing=locked \
    cargo build --locked --release -p utopia-server

# ---- 运行 ----
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl poppler-utils poppler-data && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /src/target/release/utopia-server /usr/local/bin/utopia-server
COPY --from=web /src/dist /app/web-dist
ENV UTOPIA_WEB_DIST=/app/web-dist
EXPOSE 1516
CMD ["utopia-server"]
