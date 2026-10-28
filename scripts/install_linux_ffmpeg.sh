#!/bin/sh
# Explicit, optional source build. Setup itself never downloads media tools.
set -eu
[ "$(uname -s)" = Linux ] || { echo 'This build helper is for Linux.' >&2; exit 1; }
if [ "$#" -ne 1 ]; then
  echo 'Usage: sh scripts/install_linux_ffmpeg.sh /absolute/external/install/prefix' >&2
  exit 2
fi
prefix=$1
case "$prefix" in /*) ;; *) echo 'Use an absolute install prefix.' >&2; exit 2 ;; esac
for tool in curl sha256sum tar make cc pkg-config nasm python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing build tool: $tool" >&2; exit 1; }
done
version=9.0.1
checksum=cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635
build_dir=$(mktemp -d)
trap 'rm -rf "$build_dir"' EXIT HUP INT TERM
cd "$build_dir"
curl --fail --location --retry 3 "https://ffmpeg.org/releases/ffmpeg-$version.tar.xz" -o source.tar.xz
printf '%s  source.tar.xz\n' "$checksum" | sha256sum -c -
tar -xf source.tar.xz
cd "ffmpeg-$version"
./configure --prefix="$prefix" --disable-debug --disable-doc --disable-ffplay \
  --enable-gpl --enable-libmp3lame --enable-libx264 --enable-libass --enable-libfreetype \
  --enable-libharfbuzz --enable-libfontconfig
make -j "${IMAGINE_FFMPEG_BUILD_JOBS:-2}"
make install
printf '\nInstalled FFmpeg %s. Put %s/bin first on PATH.\n' "$version" "$prefix"
