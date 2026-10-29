#!/usr/bin/env bash
# Build the wirelog engine from source for machines where the pyrewire wheel
# ships no usable library (Intel Mac, 2026-10). Linux CI uses the wheel as is.
#
# Result: vendor/wirelog/build/libwirelog.1.dylib
# Then:   export WIRELOG_LIB="$PWD/vendor/wirelog/build/libwirelog.1.dylib"
#
# Requires: git, curl, a C11 compiler (Xcode CLT), and meson + ninja in the
# active Python environment (pip install meson ninja).
set -euo pipefail

WIRELOG_TAG="${WIRELOG_TAG:-v0.70.0}"
WIRELOG_REPO="https://github.com/semantic-reasoning/wirelog.git"
XXHASH_VERSION="0.8.4"
XXHASH_SHA256="5738270935e7c3d38a79b3adf7c9692566ce7895a25f67de43ad52ab504acd32"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/vendor/wirelog"

if [ ! -d "$SRC/.git" ]; then
  mkdir -p "$ROOT/vendor"
  git clone --depth 1 --branch "$WIRELOG_TAG" "$WIRELOG_REPO" "$SRC"
fi

CACHE="$SRC/subprojects/packagecache"
mkdir -p "$CACHE"
TARBALL="$CACHE/xxHash-$XXHASH_VERSION.tar.gz"
if [ ! -f "$TARBALL" ]; then
  curl -sSL "https://github.com/Cyan4973/xxHash/archive/refs/tags/v$XXHASH_VERSION.tar.gz" -o "$TARBALL"
fi
echo "$XXHASH_SHA256  $TARBALL" | shasum -a 256 -c -

cd "$SRC"
if [ ! -d build ]; then
  meson setup build --buildtype=release -Dtests=false -Dwirelog_log_max_level=error
fi
meson compile -C build

LIB="$SRC/build/libwirelog.1.dylib"
[ -f "$LIB" ] || LIB="$SRC/build/libwirelog.so.1"
echo
echo "Built: $LIB"
echo "export WIRELOG_LIB=\"$LIB\""
