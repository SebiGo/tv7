#!/bin/sh
# Download the Raspberry Pi build of FFmpeg (V4L2-request + SAND support) and verify it completely:
#   signing key (fingerprint pinned) -> InRelease (gpgv) -> Packages.gz (SHA256 from InRelease) -> each .deb (SHA256 from Packages).
# trixie's apt rejects the archive's key policy, so apt is not used for this archive; the chain is verified here with gpgv instead.
set -eu
BASE=https://archive.raspberrypi.com/debian
SUITE=trixie
FPR=CF8A1AF502A2AA2D763BAE7E82B129927FA3303E
OUT=/pi-debs
PKGS="${PKGS:-libavcodec61 libavformat61 libavfilter10 libavutil59 libswscale8 libswresample5 libavdevice61 libpostproc58}"
mkdir -p "$OUT" /tmp/pi && cd /tmp/pi

curl -fsSL "$BASE/raspberrypi.gpg.key" -o key.asc
gpg --show-keys --with-colons key.asc | awk -F: '$1=="fpr"{print $10}' | grep -qx "$FPR" || { echo "ERROR: unexpected signing key"; exit 1; }
gpg --dearmor < key.asc > pi.gpg

curl -fsSL "$BASE/dists/$SUITE/InRelease" -o InRelease
gpgv --keyring ./pi.gpg --output Release InRelease
echo "InRelease signature verified"

HASH=$(awk '/^SHA256:/{f=1;next} /^[A-Za-z0-9-]+:/{f=0} f && $3=="main/binary-arm64/Packages.gz"{print $1}' Release)
[ -n "$HASH" ] || { echo "ERROR: no hash for Packages.gz in Release"; exit 1; }
curl -fsSL "$BASE/dists/$SUITE/main/binary-arm64/Packages.gz" -o Packages.gz
echo "$HASH  Packages.gz" | sha256sum -c -
gunzip -f Packages.gz

for p in $PKGS; do
  # shellcheck disable=SC2046  # split on purpose: file name and checksum become $1 and $2
  set -- $(awk -v RS= -v pkg="$p" '$0 ~ ("(^|\n)Package: " pkg "\n") { match($0,/\nFilename: [^\n]+/); f=substr($0,RSTART+11,RLENGTH-11); match($0,/\nSHA256: [^\n]+/); h=substr($0,RSTART+9,RLENGTH-9); print f, h; exit }' Packages)
  [ $# -eq 2 ] || { echo "ERROR: $p not found in Packages"; exit 1; }
  curl -fsSL "$BASE/$1" -o "$OUT/$(basename "$1")"
  echo "$2  $OUT/$(basename "$1")" | sha256sum -c -
done
echo "all Raspberry Pi FFmpeg packages verified:"; ls "$OUT"
