#!/usr/bin/env bash
# Download the Moli engine archive on the host into docker/scraper-browser/vendor/ and verify its sha256.
# The Docker builder on this host cannot fetch GitHub releases itself. Skips the download when a file
# with the right checksum is already present.
set -euo pipefail

VERSION="v1.1.15"
ASSET="moli-aarch64-unknown-linux-gnu.tar.gz"
SHA256="ddee0fc53b2d75bfabf59a1bf755d63c2d7fafce31435ca6a3958fbbb4a2d047"
# Default release URL for the pinned version; override with MOLI_URL.
URL="${MOLI_URL:-https://github.com/lexmount/moli/releases/download/${VERSION}/${ASSET}}"
DEST_DIR="$(cd "$(dirname "$0")/.." && pwd)/docker/scraper-browser/vendor"
DEST="${DEST_DIR}/${ASSET}"

arch="$(uname -m)"
case "${arch}" in
  arm64 | aarch64) ;;
  *) echo "fetch_moli.sh: only aarch64 is supported (this host is ${arch})" >&2; exit 1 ;;
esac

sum() { shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1 || sha256sum "$1" | cut -d' ' -f1; }

mkdir -p "${DEST_DIR}"
if [[ -f "${DEST}" && "$(sum "${DEST}")" == "${SHA256}" ]]; then
  echo "fetch_moli.sh: ${DEST} already present and verified"
  exit 0
fi

tmp="$(mktemp "${DEST_DIR}/.download.XXXXXX")"
trap 'rm -f "${tmp}"' EXIT
curl --fail --location --silent --show-error --output "${tmp}" "${URL}"
if [[ "$(sum "${tmp}")" != "${SHA256}" ]]; then
  echo "fetch_moli.sh: checksum mismatch for ${URL}" >&2
  exit 1
fi
mv "${tmp}" "${DEST}"
trap - EXIT
echo "fetch_moli.sh: downloaded and verified ${DEST}"
