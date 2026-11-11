#!/bin/sh
# Install signed Debian Bookworm packages with bounded HTTPS mirror fallback.
# Only used in Docker image builds; never changes the host's APT settings.
set -eu
[ "$#" -gt 0 ] || { echo "APT: packages required" >&2; exit 2; }

primary="${APT_PRIMARY_DEBIAN_URL:-https://mirror.arvancloud.ir/debian}"
primary_security="${APT_PRIMARY_SECURITY_URL:-https://mirror.arvancloud.ir/debian-security}"
fallback="${APT_FALLBACK_DEBIAN_URL:-https://mirror.metanet.ch/debian}"
fallback_security="${APT_FALLBACK_SECURITY_URL:-https://mirror.metanet.ch/debian-security}"
last="${APT_LAST_DEBIAN_URL:-https://mirrors.huaweicloud.com/repository/debian}"
last_security="${APT_LAST_SECURITY_URL:-https://mirrors.huaweicloud.com/repository/debian-security}"

# Only full HTTPS URLs made of unambiguous URI characters are accepted.
for uri in "$primary" "$primary_security" "$fallback" "$fallback_security" "$last" "$last_security"; do
    case "$uri" in
        https://* ) ;;
        * ) echo "APT mirror must use HTTPS" >&2; exit 2 ;;
    esac
    case "$uri" in
        *[!a-zA-Z0-9:/._~%-]* ) echo "APT mirror contains unsafe characters" >&2; exit 2 ;;
    esac
done

keyring=/usr/share/keyrings/debian-archive-keyring.gpg
[ -r "$keyring" ] || { echo "Debian archive keyring missing" >&2; exit 1; }
sources=/etc/apt/sources.list.d/debian.sources

attempt() {
    label="$1"; main_url="$2"; security_url="$3"
    shift 3
    echo "APT: trying $label signed Bookworm mirrors"
    # Replace upstream sources rather than add extra sources that could still time out.
    rm -f /etc/apt/sources.list
    cat > "$sources" <<EOF
Types: deb
URIs: $main_url
Suites: bookworm bookworm-updates
Components: main
Signed-By: $keyring

Types: deb
URIs: $security_url
Suites: bookworm-security
Components: main
Signed-By: $keyring
EOF
    rm -rf /var/lib/apt/lists/*
    apt-get -o APT::Update::Error-Mode=any \
        -o Acquire::Retries=1 \
        -o Acquire::https::Timeout=25 \
        update || return 1
    DEBIAN_FRONTEND=noninteractive apt-get \
        -o Acquire::Retries=1 -o Acquire::https::Timeout=25 \
        install -y --no-install-recommends "$@" || return 1
}

if attempt "ArvanCloud" "$primary" "$primary_security" "$@"; then
    echo "APT: ArvanCloud succeeded"
elif attempt "Metanet" "$fallback" "$fallback_security" "$@"; then
    echo "APT: Metanet succeeded"
elif attempt "HuaweiCloud" "$last" "$last_security" "$@"; then
    echo "APT: HuaweiCloud succeeded"
else
    echo "APT: all signed Bookworm mirrors failed" >&2
    exit 1
fi
rm -rf /var/lib/apt/lists/*
