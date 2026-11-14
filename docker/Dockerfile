# ---- 前端构建 ----
# Docker Hub registry mirror is configurable per stage. The Rust/runtime stages
# must remain on Debian Bookworm to preserve glibc compatibility.
ARG NODE_BASE_IMAGE=docker.arvancloud.ir/node:20-slim
ARG RUST_BASE_IMAGE=docker.arvancloud.ir/rust:1.99.1-slim-bookworm
ARG DEBIAN_BASE_IMAGE=docker.arvancloud.ir/debian:bookworm-slim
# Rust's official Bookworm image already includes Debian CA roots; the minimal
# debian:bookworm-slim runtime may not. Use a small independent trust stage so
# the runtime's APT TLS bootstrap does not wait for cargo compilation.
FROM ${RUST_BASE_IMAGE} AS apt-trust
RUN test -s /etc/ssl/certs/ca-certificates.crt

FROM ${NODE_BASE_IMAGE} AS web
ARG NPM_REGISTRY_URL=https://package-mirror.liara.ir/repository/npm/
ARG NPM_FALLBACK_REGISTRY_URL=https://registry.npmjs.org/
WORKDIR /src
RUN corepack enable
# Keep the committed pnpm lockfile authoritative. The fallback only changes the
# registry, never the package versions or lockfile.
RUN corepack prepare pnpm@10.2.1 --activate
COPY web/package.json web/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    (pnpm install --frozen-lockfile --registry="${NPM_REGISTRY_URL}" \
    || pnpm install --frozen-lockfile --registry="${NPM_FALLBACK_REGISTRY_URL}")
COPY web/ ./
RUN pnpm build

# ---- 后端构建 ----
# 发行版必须和运行阶段钉死在同一个：rust:1-slim 会跟着上游滚（现已是 trixie/glibc 2.41），
# 编出的二进制便要求 GLIBC_2.38，而 bookworm 只有 2.36——镜像构建照样成功，
# 容器一启动就 "version `GLIBC_2.38' not found"。
FROM ${RUST_BASE_IMAGE} AS build
ARG APT_PRIMARY_DEBIAN_URL=https://mirror.arvancloud.ir/debian
ARG APT_PRIMARY_SECURITY_URL=https://mirror.arvancloud.ir/debian-security
ARG APT_FALLBACK_DEBIAN_URL=https://mirror.metanet.ch/debian
ARG APT_FALLBACK_SECURITY_URL=https://mirror.metanet.ch/debian-security
ARG APT_LAST_DEBIAN_URL=https://mirrors.huaweicloud.com/repository/debian
ARG APT_LAST_SECURITY_URL=https://mirrors.huaweicloud.com/repository/debian-security
ENV APT_PRIMARY_DEBIAN_URL=${APT_PRIMARY_DEBIAN_URL} \
    APT_PRIMARY_SECURITY_URL=${APT_PRIMARY_SECURITY_URL} \
    APT_FALLBACK_DEBIAN_URL=${APT_FALLBACK_DEBIAN_URL} \
    APT_FALLBACK_SECURITY_URL=${APT_FALLBACK_SECURITY_URL} \
    APT_LAST_DEBIAN_URL=${APT_LAST_DEBIAN_URL} \
    APT_LAST_SECURITY_URL=${APT_LAST_SECURITY_URL}
# Limit concurrent rustc processes on resource-constrained development hosts.
# Override via SOORIN_BUILD_JOBS in the isolated Compose file.
ARG CARGO_BUILD_JOBS=1
WORKDIR /src
COPY docker/install-debian-packages.sh /usr/local/bin/install-debian-packages
RUN sh /usr/local/bin/install-debian-packages pkg-config
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
FROM ${DEBIAN_BASE_IMAGE}
ARG APT_PRIMARY_DEBIAN_URL=https://mirror.arvancloud.ir/debian
ARG APT_PRIMARY_SECURITY_URL=https://mirror.arvancloud.ir/debian-security
ARG APT_FALLBACK_DEBIAN_URL=https://mirror.metanet.ch/debian
ARG APT_FALLBACK_SECURITY_URL=https://mirror.metanet.ch/debian-security
ARG APT_LAST_DEBIAN_URL=https://mirrors.huaweicloud.com/repository/debian
ARG APT_LAST_SECURITY_URL=https://mirrors.huaweicloud.com/repository/debian-security
ENV APT_PRIMARY_DEBIAN_URL=${APT_PRIMARY_DEBIAN_URL} \
    APT_PRIMARY_SECURITY_URL=${APT_PRIMARY_SECURITY_URL} \
    APT_FALLBACK_DEBIAN_URL=${APT_FALLBACK_DEBIAN_URL} \
    APT_FALLBACK_SECURITY_URL=${APT_FALLBACK_SECURITY_URL} \
    APT_LAST_DEBIAN_URL=${APT_LAST_DEBIAN_URL} \
    APT_LAST_SECURITY_URL=${APT_LAST_SECURITY_URL}
# Bootstrap HTTPS trust before apt-get: the base runtime layer has no usable
# ca-certificates bundle yet. Source is the same pinned Bookworm Rust base,
# independently of its expensive cargo build stage. Never disable TLS checks.
COPY --from=apt-trust /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY docker/install-debian-packages.sh /usr/local/bin/install-debian-packages
RUN test -s /etc/ssl/certs/ca-certificates.crt \
    && sh /usr/local/bin/install-debian-packages ca-certificates curl poppler-utils poppler-data python3
WORKDIR /app
COPY soorin/ /app/soorin/
COPY --from=build /src/target/release/utopia-server /usr/local/bin/utopia-server
COPY --from=web /src/dist /app/web-dist
RUN groupadd --gid 65532 soorin && useradd --uid 65532 --gid 65532 --no-create-home soorin \
    && mkdir -p /app/data && chown 65532:65532 /app/data
LABEL org.opencontainers.image.title="Soorin Bitemporal Knowledge Graph"
ENV UTOPIA_WEB_DIST=/app/web-dist UTOPIA_DATA_DIR=/app/data
USER 65532:65532
EXPOSE 1516
CMD ["utopia-server"]
