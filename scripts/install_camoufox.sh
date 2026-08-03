#!/usr/bin/env bash
set -euo pipefail

CAMOUFOX_VERSION="135.0.1-beta.24"
CAMOUFOX_BASE_VERSION="135.0.1"
CAMOUFOX_RELEASE="beta.24"
CAMOUFOX_SHA256="61e1ec455e021720af38a5cc5ff7566121363cb5b82b72f24e381ba2676a4888"
CAMOUFOX_ARCHIVE="camoufox-${CAMOUFOX_VERSION}-lin.x86_64.zip"
CAMOUFOX_URL="https://github.com/daijro/camoufox/releases/download/v${CAMOUFOX_VERSION}/${CAMOUFOX_ARCHIVE}"

CACHE_DIR="$(python -c 'from camoufox.pkgman import INSTALL_DIR; print(INSTALL_DIR)')"

if [ -x "$CACHE_DIR/camoufox-bin" ]; then
  INSTALLED_VERSION="$(python -c 'from camoufox.pkgman import installed_verstr; print(installed_verstr())' 2>/dev/null || true)"
  if [ "$INSTALLED_VERSION" = "$CAMOUFOX_VERSION" ]; then
    echo "Using cached Camoufox v${INSTALLED_VERSION} at ${CACHE_DIR}"
    exit 0
  fi
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

echo "Installing pinned Camoufox v${CAMOUFOX_VERSION}"
curl --fail --location --retry 3 --retry-delay 2 \
  --output "${TEMP_DIR}/${CAMOUFOX_ARCHIVE}" \
  "$CAMOUFOX_URL"

echo "${CAMOUFOX_SHA256}  ${TEMP_DIR}/${CAMOUFOX_ARCHIVE}" | sha256sum --check --status

rm -rf "$CACHE_DIR"
mkdir -p "$CACHE_DIR"
unzip -q "${TEMP_DIR}/${CAMOUFOX_ARCHIVE}" -d "$CACHE_DIR"
printf '{"version":"%s","release":"%s"}\n' \
  "$CAMOUFOX_BASE_VERSION" "$CAMOUFOX_RELEASE" > "$CACHE_DIR/version.json"
chmod -R 755 "$CACHE_DIR"

test -x "$CACHE_DIR/camoufox-bin"
INSTALLED_VERSION="$(python -c 'from camoufox.pkgman import installed_verstr; print(installed_verstr())')"
test "$INSTALLED_VERSION" = "$CAMOUFOX_VERSION"
echo "Installed Camoufox v${INSTALLED_VERSION} at ${CACHE_DIR}"
