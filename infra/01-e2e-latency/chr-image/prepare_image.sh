#!/usr/bin/env bash
# Download a MikroTik CHR image, verify the vendor SHA-256, convert raw -> QCOW2.
# Runs on the Linux / Control Host; output stays OUTSIDE the repo.
#
#   ./prepare_image.sh [version] [arm64|x86_64]
#   -> prints image_path / image_sha256 lines to paste into terraform.tfvars
set -euo pipefail

VERSION="${1:-7.25.1}"
ARCH="${2:-arm64}"
case "$ARCH" in
  arm64)  NAME="chr-${VERSION}-arm64" ;;
  x86_64) NAME="chr-${VERSION}" ;;
  *) echo "arch must be arm64 or x86_64" >&2; exit 2 ;;
esac

BASE="https://download.mikrotik.com/routeros/${VERSION}"
WORK="${XDG_CACHE_HOME:-$HOME/.cache}/soar-net-lab/chr/${VERSION}-${ARCH}"
mkdir -p "$WORK/dl"
cd "$WORK"

command -v qemu-img >/dev/null || { echo "qemu-img not found (apt install qemu-utils)" >&2; exit 1; }

curl -fsSL -o "dl/${NAME}.img.zip"        "${BASE}/${NAME}.img.zip"
curl -fsSL -o "dl/${NAME}.img.zip.sha256" "${BASE}/${NAME}.img.zip.sha256"

expected="$(grep -oE '[0-9a-f]{64}' "dl/${NAME}.img.zip.sha256" | head -1)"
actual="$(sha256sum "dl/${NAME}.img.zip" | cut -d' ' -f1)"
if [[ -z "$expected" || "$expected" != "$actual" ]]; then
  echo "SHA-256 mismatch: expected=${expected:-none} actual=$actual" >&2
  exit 1
fi
echo "vendor sha256 OK: $actual" >&2

# Extract with Python's zipfile (isolated mode), refusing path traversal.
python3 -I - "dl/${NAME}.img.zip" "dl" <<'PY'
import sys, zipfile, os
zf, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(zf) as z:
    for n in z.namelist():
        if os.path.isabs(n) or ".." in n.split("/"):
            sys.exit(f"unsafe path in zip: {n}")
    z.extractall(out)
PY

RAW="dl/${NAME}.img"
[[ -f "$RAW" ]] || { echo "expected $RAW in archive" >&2; exit 1; }

qemu-img convert -f raw -O qcow2 "$RAW" "${NAME}.qcow2"
qemu-img check -q "${NAME}.qcow2"

size=$(stat -c %s "${NAME}.qcow2")
sha=$(sha256sum "${NAME}.qcow2" | cut -d' ' -f1)
echo "qcow2 size: $((size / 1024 / 1024)) MiB (virtual: $(qemu-img info --output=json "${NAME}.qcow2" | python3 -I -c 'import json,sys;print(json.load(sys.stdin)["virtual-size"]//2**20)') MiB)" >&2

cat <<EOF
chr_version  = "${VERSION}"
chr_arch     = "${ARCH}"
image_path   = "${WORK}/${NAME}.qcow2"
image_sha256 = "${sha}"
EOF
