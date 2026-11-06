#!/bin/bash
# Optional native library build only. This does NOT enable packetFlow transport.
set -euo pipefail
project="$(cd "$(dirname "$0")/.." && pwd)"
vendor="$project/../vendor/hev-socks5-tunnel"
expected=c5584feca8f6df70ee53eb2879e034b849a3d15a
actual="$(git -C "$vendor" rev-parse HEAD)"
test "$actual" = "$expected" || { echo "Expected HEV 2.19.3 commit $expected" >&2; exit 1; }
xcrun --find clang >/dev/null
work="$project/build/hev-2.19.3"
test ! -e "$work" || { echo "Move existing $work aside first" >&2; exit 1; }
mkdir -p "$work"
cp -R "$vendor/." "$work/"
cd "$work"
for dependency in lwip yaml hev-task-system; do
    test -f "third-part/$dependency/Makefile" || { echo "Populate pinned HEV submodules first: $dependency" >&2; exit 1; }
done
build_slice() {
    sdk="$1"; arch="$2"
    make PP="xcrun --sdk $sdk clang" CC="xcrun --sdk $sdk clang" \
        CFLAGS="-arch $arch -m$sdk-version-min=16.0" \
        LFLAGS="-arch $arch -m$sdk-version-min=16.0" static
    mkdir -p "slices/$sdk-$arch"
    libtool -static -o "slices/$sdk-$arch/libhev.a" bin/libhev-socks5-tunnel.a \
        third-part/lwip/bin/liblwip.a third-part/yaml/bin/libyaml.a \
        third-part/hev-task-system/bin/libhev-task-system.a
    make clean
}
build_slice iphoneos arm64
build_slice iphonesimulator arm64
build_slice iphonesimulator x86_64
mkdir -p slices/simulator include/HevSocks5Tunnel
lipo -create slices/iphonesimulator-arm64/libhev.a slices/iphonesimulator-x86_64/libhev.a -output slices/simulator/libhev.a
cp src/hev-main.h module.modulemap include/HevSocks5Tunnel/
xcodebuild -create-xcframework \
    -library slices/iphoneos-arm64/libhev.a -headers include \
    -library slices/simulator/libhev.a -headers include \
    -output "$project/build/HevSocks5Tunnel.xcframework"
echo "Built MIT HEV 2.19.3 candidate; public packetFlow adapter + local SOCKS/engine integration remain unimplemented."
