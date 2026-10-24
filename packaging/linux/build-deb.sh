#!/usr/bin/env bash
# Packages dist/Simple-Chat/ (already built by PyInstaller, onedir mode)
# into a .deb that installs to /opt/simple-chat and adds a proper menu
# entry + icon, so it behaves like a native app rather than a dropped
# binary. Uses dpkg-deb directly, which ships with Debian-based distros
# (Pop!_OS included) — no extra tool to install in CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLE="$ROOT/dist/Simple-Chat"
VERSION="$(grep -o '__version__ = "[^"]*"' "$ROOT/src/simple_chat/__init__.py" | cut -d'"' -f2)"
ARCH="$(dpkg --print-architecture)"
PKG_ROOT="$ROOT/dist/deb-staging"
OUT="$ROOT/dist/simple-chat_${VERSION}_${ARCH}.deb"

if [ ! -d "$BUNDLE" ]; then
  echo "error: $BUNDLE not found — run PyInstaller first" >&2
  exit 1
fi

rm -rf "$PKG_ROOT" "$OUT"
mkdir -p "$PKG_ROOT/DEBIAN"
mkdir -p "$PKG_ROOT/opt/simple-chat"
mkdir -p "$PKG_ROOT/usr/bin"
mkdir -p "$PKG_ROOT/usr/share/applications"

cp -R "$BUNDLE"/. "$PKG_ROOT/opt/simple-chat/"
ln -s /opt/simple-chat/Simple-Chat "$PKG_ROOT/usr/bin/simple-chat"
cp "$ROOT/packaging/linux/simple-chat.desktop" "$PKG_ROOT/usr/share/applications/"

for size in 16 32 48 64 128 256 512; do
  dir="$PKG_ROOT/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$dir"
  cp "$ROOT/packaging/icons/icon_${size}.png" "$dir/simple-chat.png"
done

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: simple-chat
Version: $VERSION
Section: misc
Priority: optional
Architecture: $ARCH
Depends: libegl1, libxkbcommon0, libxcb-cursor0, libfontconfig1, libdbus-1-3
Maintainer: Mike Hellyer
Description: Pass messages between your computers on the local network
 A simple chat between your own machines on the same network: no
 accounts, no internet and no server. Machines running Simple-Chat
 find each other by themselves, and messages to a machine that's
 switched off are delivered when it's next on.
EOF

dpkg-deb --build --root-owner-group "$PKG_ROOT" "$OUT"
rm -rf "$PKG_ROOT"

echo "wrote $OUT"
