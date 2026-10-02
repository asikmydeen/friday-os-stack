#!/bin/bash
# Runs inside a privileged linux/amd64 Debian container. Do not run this on the Mac.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

stage() { printf '%s\n' "$1" > /out/stage; echo "== $1 =="; }

# mount(8) reuses a leftover read-only loop and then the rootfs cannot be written.
detach_loops() {
  local image="$1" dev
  while read -r dev; do
    [ -n "$dev" ] || continue
    losetup -d "$dev" || true
  done < <(losetup -j "$image" | awk -F: '{print $1}')
}

assert_payload_present() {
  # A loaded graph is the copy that boots. A leftover sparse tar must not
  # hide that graph, and it must not ride along beside it.
  local tar="$ROOT/usr/lib/friday/images/core-images.tar"
  local graph="$ROOT/var/lib/docker"
  if [ -d "$graph/overlay2" ] || [ -d "$graph/image" ]; then
    local used
    used=$(du -s -B1 "$graph" | awk '{print $1}')
    echo "docker graph bytes=$used"
    if [ "$used" -ge 3000000000 ]; then
      rm -f "$tar"
      return
    fi
  fi
  if [ -f "$tar" ]; then
    local src dst blocks alloc
    src=$(stat -c '%s' /out/payload/core-images.tar)
    dst=$(stat -c '%s' "$tar")
    blocks=$(stat -c '%b' "$tar")
    alloc=$((blocks * 512))
    echo "packed tar size=$dst alloc=$alloc source=$src"
    if [ "$dst" != "$src" ] || [ "$alloc" -lt $((src * 9 / 10)) ]; then
      echo "core image tar is not fully on the root filesystem" >&2
      exit 1
    fi
    return
  fi
  echo "the root filesystem has neither the core images nor their tar" >&2
  exit 1
}

load_images() {
  # One copy of the images, in the rootfs graph. The tar stays on the build
  # machine. If dockerd cannot load it, the tar is packed and loaded on first start.
  # A graph left by an older payload is loaded again when the tar hash changes.
  local stamp="$ROOT/usr/lib/friday/payload.sha256"
  local want have used
  want=$(sha256sum /out/payload/core-images.tar | awk '{print $1}')
  have=$(cat "$stamp" 2>/dev/null || true)
  if [ -d "$ROOT/var/lib/docker/overlay2" ] || [ -d "$ROOT/var/lib/docker/image" ]; then
    used=$(du -s -B1 "$ROOT/var/lib/docker" | awk '{print $1}')
    echo "docker graph bytes=$used"
    if [ "$used" -ge 3000000000 ] && [ "$have" = "$want" ]; then
      echo "payload hash matches the loaded graph"
      rm -f "$ROOT/usr/lib/friday/images/core-images.tar"
      return
    fi
  fi
  echo "loading core images into the rootfs"
  if ! command -v dockerd >/dev/null 2>&1 || ! command -v docker >/dev/null 2>&1; then
    apt-get update
    apt-get install -y --no-install-recommends docker.io docker-cli
  fi
  mkdir -p "$ROOT/var/lib/docker" /tmp/friday-docker
  dockerd \
    --data-root="$ROOT/var/lib/docker" \
    --exec-root=/tmp/friday-docker \
    --host=unix:///tmp/friday-build.sock \
    --pidfile=/tmp/friday-dockerd.pid \
    --iptables=false \
    --ip6tables=false \
    >/tmp/friday-dockerd.log 2>&1 &
  ready=0
  info_err=/tmp/friday-docker-info.txt
  for _ in $(seq 1 90); do
    if docker --host=unix:///tmp/friday-build.sock info >"$info_err" 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  loaded=1
  if [ "$ready" -eq 1 ]; then
    if docker --host=unix:///tmp/friday-build.sock load -i /out/payload/core-images.tar; then
      docker --host=unix:///tmp/friday-build.sock image prune -f >/dev/null || true
      mkdir -p "$ROOT/usr/lib/friday"
      printf '%s\n' "$want" > "$stamp"
      loaded=0
    fi
  else
    echo "dockerd did not accept a client" >&2
    cat "$info_err" >&2 || true
  fi
  if [ -f /tmp/friday-dockerd.pid ]; then
    kill "$(cat /tmp/friday-dockerd.pid)" 2>/dev/null || true
    for _ in $(seq 1 120); do
      if [ ! -f /tmp/friday-dockerd.pid ]; then
        break
      fi
      if ! kill -0 "$(cat /tmp/friday-dockerd.pid)" 2>/dev/null; then
        break
      fi
      sleep 1
    done
    if [ -f /tmp/friday-dockerd.pid ]; then
      kill -9 "$(cat /tmp/friday-dockerd.pid)" 2>/dev/null || true
    fi
  fi
  sync
  if [ -r /proc/mounts ]; then
    mounts=$(awk '{print $2}' /proc/mounts | grep -F "$ROOT/var/lib/docker" || true)
    if [ -n "$mounts" ]; then
      printf '%s\n' "$mounts" | sort -r | while read -r mount; do
        [ -n "$mount" ] || continue
        umount "$mount" || umount -l "$mount" || true
      done
    fi
  fi
  if [ "$loaded" -ne 0 ]; then
    echo "image load failed; packing the tar instead" >&2
    tail -n 40 /tmp/friday-dockerd.log >&2 || true
    rm -rf "$ROOT/var/lib/docker"
    mkdir -p "$ROOT/usr/lib/friday/images"
    cp --sparse=never /out/payload/core-images.tar "$ROOT/usr/lib/friday/images/core-images.tar"
    sync
  fi
  assert_payload_present
}

make_lab() {
  # A bootable installed-role disk for the local QEMU check. The USB image
  # stays the installer. Serial input is enabled only on this lab disk.
  echo "building installed lab disk"
  rm -f /out/work/lab-root.img /out/work/installed-lab.img /out/work/lab-data.img /out/work/lab-efi.img
  cp --sparse=never "$ROOTIMG" /out/work/lab-root.img
  tune2fs -L friday-a /out/work/lab-root.img
  python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "/src")
from image.disks import FSTAB_INSTALLED, grub_installed
Path("/tmp/lab-fstab").write_text(FSTAB_INSTALLED)
Path("/tmp/lab-grub.cfg").write_text(grub_installed())
PY
  sed 's#TTYPath=/dev/console#TTYPath=/dev/ttyS0#' /src/image/assets/friday-setup.service > /tmp/lab-setup.service
  printf 'installed\n' > /tmp/lab-role
  debugfs -w -R "rm etc/friday-role" /out/work/lab-root.img || true
  debugfs -w -R "write /tmp/lab-role etc/friday-role" /out/work/lab-root.img
  debugfs -w -R "rm etc/fstab" /out/work/lab-root.img || true
  debugfs -w -R "write /tmp/lab-fstab etc/fstab" /out/work/lab-root.img
  debugfs -w -R "rm boot/grub/grub.cfg" /out/work/lab-root.img || true
  debugfs -w -R "write /tmp/lab-grub.cfg boot/grub/grub.cfg" /out/work/lab-root.img
  debugfs -w -R "rm etc/systemd/system/friday-setup.service" /out/work/lab-root.img || true
  debugfs -w -R "write /tmp/lab-setup.service etc/systemd/system/friday-setup.service" /out/work/lab-root.img
  role=$(debugfs -R "cat etc/friday-role" /out/work/lab-root.img)
  printf '%s' "$role" | grep -qx 'installed'
  debugfs -R "cat etc/systemd/system/friday-setup.service" /out/work/lab-root.img | grep -q 'TTYPath=/dev/ttyS0'
  set +e
  e2fsck -fy /out/work/lab-root.img
  rc=$?
  set -e
  if [ "$rc" -gt 1 ]; then
    echo "lab e2fsck failed: $rc" >&2
    exit 1
  fi
  cp /out/work/efi.img /out/work/lab-efi.img
  mdel -i /out/work/lab-efi.img ::/EFI/BOOT/grub.cfg
  mcopy -i /out/work/lab-efi.img /tmp/lab-grub.cfg ::/EFI/BOOT/grub.cfg
  truncate -s 2048M /out/work/lab-data.img
  mkfs.ext4 -F -L friday-data /out/work/lab-data.img
  data_mib=2048
  root_end=$((513 + root_mib))
  data_end=$((root_end + data_mib))
  lab_disk_mib=$((data_end + 1))
  rm -f /out/work/installed-lab.img
  truncate -s "${lab_disk_mib}M" /out/work/installed-lab.img
  parted -s /out/work/installed-lab.img mklabel gpt
  parted -s /out/work/installed-lab.img mkpart friday-efi fat32 1MiB 513MiB
  parted -s /out/work/installed-lab.img set 1 esp on
  parted -s /out/work/installed-lab.img mkpart friday-a ext4 513MiB "${root_end}MiB"
  parted -s /out/work/installed-lab.img mkpart friday-data ext4 "${root_end}MiB" "${data_end}MiB"
  parted -m /out/work/installed-lab.img unit B print > /out/work/lab-parted.txt
  python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "/src")
from image.disks import parse_parted
rows = parse_parted(Path("/out/work/lab-parted.txt").read_text())
if len(rows) != 3 or rows[0]["end"] >= rows[1]["start"] or rows[1]["end"] >= rows[2]["start"]:
    raise SystemExit("lab partitions overlap: %s" % rows)
if "esp" not in rows[0]["flags"]:
    raise SystemExit("lab efi partition has no esp flag")
Path("/out/work/lab-spans").write_text(
    "%s %s\n%s %s\n%s %s\n"
    % (
        rows[0]["start"], rows[0]["size"],
        rows[1]["start"], rows[1]["size"],
        rows[2]["start"], rows[2]["size"],
    )
)
PY
  {
    read -r lab_efi_start lab_efi_size
    read -r lab_root_start lab_root_size
    read -r lab_data_start lab_data_size
  } < /out/work/lab-spans
  lab_efi_file=$(stat -c '%s' /out/work/lab-efi.img)
  lab_root_file=$(stat -c '%s' /out/work/lab-root.img)
  lab_data_file=$(stat -c '%s' /out/work/lab-data.img)
  if [ "$lab_efi_size" != "$lab_efi_file" ] || [ "$lab_root_size" != "$lab_root_file" ] || [ "$lab_data_size" != "$lab_data_file" ]; then
    echo "lab partition size does not match the filesystem image" >&2
    echo "efi $lab_efi_size/$lab_efi_file root $lab_root_size/$lab_root_file data $lab_data_size/$lab_data_file" >&2
    exit 1
  fi
  dd if=/out/work/lab-efi.img of=/out/work/installed-lab.img bs=1M seek="$((lab_efi_start / 1048576))" conv=notrunc,sparse status=none
  dd if=/out/work/lab-root.img of=/out/work/installed-lab.img bs=1M seek="$((lab_root_start / 1048576))" conv=notrunc,sparse status=none
  dd if=/out/work/lab-data.img of=/out/work/installed-lab.img bs=1M seek="$((lab_data_start / 1048576))" conv=notrunc,sparse status=none
  sync
}

if [ "$(uname -m)" != "x86_64" ]; then
  echo "builder is $(uname -m), want x86_64" >&2
  exit 1
fi
if [ ! -s /out/payload/core-images.tar ] || [ ! -d /out/payload/ollama-models/models ]; then
  echo "core payload is missing. Run scripts/fetch-core.sh before this build." >&2
  exit 1
fi
if ! grep -q 'friday-os-stack/webhooks:0.1.0-amd64 linux/amd64' /out/payload/pins.txt \
  || ! grep -q 'friday-os-stack/gateway:0.1.0-amd64 linux/amd64' /out/payload/pins.txt \
  || ! grep -q 'friday-os-stack/door:0.1.0-amd64 linux/amd64' /out/payload/pins.txt \
  || ! grep -q 'friday-os-stack/mcp:0.1.0-amd64 linux/amd64' /out/payload/pins.txt \
  || ! grep -q 'friday-os-stack/browser:0.1.0-amd64 linux/amd64' /out/payload/pins.txt; then
  echo "payload pins do not include the webhook receiver, the gateway, the door, the MCP listener, and the browser session. Run scripts/fetch-core.sh." >&2
  exit 1
fi

ROOT=/build/rootfs
ROOTIMG=/out/work/root.img
mkdir -p /out/work /out/scan /build
stage tools
apt-get update
apt-get install -y --no-install-recommends \
  debootstrap parted e2fsprogs dosfstools mtools python3 git \
  ca-certificates rsync xz-utils findutils

stage probe
rm -rf /out/work/probe
mkdir -p /out/work/probe/src/etc
printf 'installer\n' > /out/work/probe/src/etc/friday-role
truncate -s 64M /out/work/probe/disk.img
parted -s /out/work/probe/disk.img mklabel gpt
parted -s /out/work/probe/disk.img mkpart friday-efi fat32 1MiB 17MiB
parted -s /out/work/probe/disk.img set 1 esp on
parted -s /out/work/probe/disk.img mkpart friday-installer ext4 17MiB 100%
parted -m /out/work/probe/disk.img unit B print > /out/work/probe/parted.txt
python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "/src")
from image.disks import parse_parted
rows = parse_parted(Path("/out/work/probe/parted.txt").read_text())
if len(rows) != 2 or rows[0]["end"] >= rows[1]["start"]:
    raise SystemExit("probe partitions overlap: %s" % rows)
Path("/out/work/probe/spans").write_text(
    "%s %s\n%s %s\n" % (rows[0]["start"], rows[0]["size"], rows[1]["start"], rows[1]["size"])
)
PY
{
  read -r efi_start efi_size
  read -r root_start root_size
} < /out/work/probe/spans
truncate -s "$efi_size" /out/work/probe/efi.img
truncate -s "$root_size" /out/work/probe/root.img
mkfs.vfat -F 32 -n FRIDAYEFI /out/work/probe/efi.img
mkfs.ext4 -d /out/work/probe/src -L friday-installer -F /out/work/probe/root.img
dd if=/out/work/probe/efi.img of=/out/work/probe/disk.img bs=512 seek="$((efi_start / 512))" conv=notrunc,sparse status=none
dd if=/out/work/probe/root.img of=/out/work/probe/disk.img bs=512 seek="$((root_start / 512))" conv=notrunc,sparse status=none
role=$(debugfs -R "cat etc/friday-role" /out/work/probe/root.img)
printf '%s' "$role" | grep -qx 'installer' || { echo "probe role was [$role]" >&2; exit 1; }

cleanup_binds() {
  for mount in "$ROOT/dev/pts" "$ROOT/dev" "$ROOT/proc" "$ROOT/sys"; do
    if [ -d "$mount" ] && mountpoint -q "$mount"; then
      umount "$mount" || umount -l "$mount" || true
    fi
  done
}
cleanup_mounts() {
  cleanup_binds
  if mountpoint -q "$ROOT"; then
    umount "$ROOT" || umount -l "$ROOT" || true
  fi
}
trap cleanup_mounts EXIT

# The root filesystem is an ext4 image, not a directory on the Mac disk.
# Extracting Debian onto the bind mount fails when tar cannot finish a package.
stage root-disk
need_bytes=$((20 * 1024 * 1024 * 1024))
if [ ! -f /out/work/stamp-debootstrap ]; then
  rm -f "$ROOTIMG"
  truncate -s "$need_bytes" "$ROOTIMG"
  mkfs.ext4 -F -L friday-installer "$ROOTIMG"
elif [ -f "$ROOTIMG" ] && [ "$(stat -c '%s' "$ROOTIMG")" -lt "$need_bytes" ]; then
  if mountpoint -q "$ROOT"; then
    umount "$ROOT" || umount -l "$ROOT"
  fi
  set +e
  e2fsck -fy "$ROOTIMG"
  rc=$?
  set -e
  if [ "$rc" -gt 1 ]; then
    echo "e2fsck before expand failed: $rc" >&2
    exit 1
  fi
  truncate -s "$need_bytes" "$ROOTIMG"
  resize2fs "$ROOTIMG"
fi
mkdir -p "$ROOT"
if mountpoint -q "$ROOT" && awk -v root="$ROOT" '$2==root && $4 ~ /^ro/' /proc/mounts | grep -q .; then
  umount "$ROOT" || umount -l "$ROOT"
fi
if ! mountpoint -q "$ROOT"; then
  detach_loops "$ROOTIMG"
  loop=$(losetup -f --show "$ROOTIMG")
  if [ "$(cat "/sys/block/${loop#/dev/}/ro")" != "0" ]; then
    echo "root image loop is read-only" >&2
    exit 1
  fi
  mount -o rw "$loop" "$ROOT"
fi
if awk -v root="$ROOT" '$2==root && $4 ~ /^ro/' /proc/mounts | grep -q .; then
  echo "root filesystem mounted read-only" >&2
  exit 1
fi

stage debootstrap
if [ ! -f /out/work/stamp-debootstrap ]; then
  debootstrap --arch=amd64 --variant=minbase stable "$ROOT" http://deb.debian.org/debian
  printf 'ok\n' > /out/work/stamp-debootstrap
fi
if [ "$(chroot "$ROOT" dpkg --print-architecture)" != "amd64" ]; then
  echo "rootfs is not amd64" >&2
  exit 1
fi

mount_root() {
  mkdir -p "$ROOT/dev" "$ROOT/proc" "$ROOT/sys" "$ROOT/dev/pts" "$ROOT/run" "$ROOT/tmp"
  mountpoint -q "$ROOT/dev" || mount --bind /dev "$ROOT/dev"
  mountpoint -q "$ROOT/proc" || mount --bind /proc "$ROOT/proc"
  mountpoint -q "$ROOT/sys" || mount --bind /sys "$ROOT/sys"
  mountpoint -q "$ROOT/dev/pts" || mount --bind /dev/pts "$ROOT/dev/pts" || true
}

PACKAGES="linux-image-amd64 systemd systemd-sysv udev dbus systemd-resolved systemd-timesyncd kmod python3 parted gdisk e2fsprogs dosfstools rsync grub-efi-amd64-bin ca-certificates tzdata iproute2 firmware-linux-free docker.io docker-cli docker-compose cage chromium iwd"
STAMP=$(printf '%s' "$PACKAGES" | sha256sum | awk '{print $1}')
mount_root
if [ "$(cat /out/work/stamp-packages 2>/dev/null || true)" != "$STAMP" ]; then
  stage packages
  printf '#!/bin/sh\nexit 101\n' > "$ROOT/usr/sbin/policy-rc.d"
  chmod 755 "$ROOT/usr/sbin/policy-rc.d"
  mkdir -p "$ROOT/etc/dpkg/dpkg.cfg.d" "$ROOT/etc/apt/apt.conf.d"
  printf 'force-unsafe-io\n' > "$ROOT/etc/dpkg/dpkg.cfg.d/unsafe-io"
  printf 'Acquire::Retries "5";\n' > "$ROOT/etc/apt/apt.conf.d/80-retries"
  ln -sfn /usr/share/zoneinfo/UTC "$ROOT/etc/localtime"
  printf 'UTC\n' > "$ROOT/etc/timezone"
  chroot "$ROOT" apt-get update
  # shellcheck disable=SC2086
  chroot "$ROOT" apt-get install -y --no-install-recommends $PACKAGES
  printf '%s\n' "$STAMP" > /out/work/stamp-packages
fi

stage configure
rm -f "$ROOT/usr/sbin/policy-rc.d" "$ROOT/etc/dpkg/dpkg.cfg.d/unsafe-io"
VERSION=$(python3 -c 'import sys; sys.path.insert(0, "/src"); from image import VERSION; print(VERSION)')
mkdir -p "$ROOT/usr/lib/friday/image" "$ROOT/etc/systemd/network" "$ROOT/etc/systemd/system" \
  "$ROOT/soul/agents" "$ROOT/soul/agents-full" "$ROOT/usr/share/doc/friday" "$ROOT/boot/grub" "$ROOT/boot/efi"
for name in __init__.py disks.py install.py setup.py provision.py console.py main.py starter.py mesh.py qdrant_bootstrap.py wifi.py kiosk.py logs.py; do
  cp "/src/image/$name" "$ROOT/usr/lib/friday/image/$name"
done
cp /src/image/qdrant_bootstrap.py "$ROOT/usr/lib/friday/qdrant_bootstrap.py"
cp /src/image/assets/core-compose.yml "$ROOT/usr/lib/friday/compose.yml"
cp /src/image/assets/compose.board.yml "$ROOT/usr/lib/friday/compose.board.yml"
mkdir -p "$ROOT/usr/lib/friday/sql" "$ROOT/usr/lib/friday/ollama-models" "$ROOT/var/lib/friday"
cp /src/sql/memories.sql "$ROOT/usr/lib/friday/sql/memories.sql"
cp /src/sql/webhooks.sql "$ROOT/usr/lib/friday/sql/webhooks.sql"
cp /src/sql/backup.sql "$ROOT/usr/lib/friday/sql/backup.sql"
cp /src/sql/approvals.sql "$ROOT/usr/lib/friday/sql/approvals.sql"
cp -a /out/payload/ollama-models/. "$ROOT/usr/lib/friday/ollama-models/"
if [ -f /out/payload/pins.txt ]; then
  cp /out/payload/pins.txt "$ROOT/usr/lib/friday/pins.txt"
fi
if [ -f /out/payload/nomic-show.txt ]; then
  cp /out/payload/nomic-show.txt "$ROOT/usr/lib/friday/nomic-show.txt"
fi
cp /src/image/assets/friday-setup.service "$ROOT/etc/systemd/system/friday-setup.service"
cp /src/image/assets/20-wired.network "$ROOT/etc/systemd/network/20-wired.network"
cp /src/image/assets/friday-omitted "$ROOT/etc/friday-omitted"
cp /src/image/assets/friday-kiosk.service "$ROOT/etc/systemd/system/friday-kiosk.service"
rm -rf "$ROOT/usr/lib/friday/wires" "$ROOT/usr/lib/friday/catalog"
mkdir -p "$ROOT/usr/lib/friday/wires" "$ROOT/usr/lib/friday/catalog"
cp /src/catalog/wires/*.yml "$ROOT/usr/lib/friday/wires/"
cp /src/catalog/__init__.py /src/catalog/discover.py /src/catalog/snapshot.py \
  /src/catalog/allowlist.py /src/catalog/PIN \
  "$ROOT/usr/lib/friday/catalog/"
rm -rf "$ROOT/usr/lib/friday/helm"
mkdir -p "$ROOT/usr/lib/friday/helm/templates"
cp /src/deploy/helm/Chart.yaml /src/deploy/helm/values.yaml /src/deploy/helm/README.md \
  "$ROOT/usr/lib/friday/helm/"
cp /src/deploy/helm/templates/workloads.yaml /src/deploy/helm/templates/pvc.yaml \
  "$ROOT/usr/lib/friday/helm/templates/"
if [ ! -s /out/payload/catalog-pin ] || [ ! -d /out/payload/catalog-snapshot/ix-dev ]; then
  rm -rf /tmp/truenas-apps /out/payload/catalog-snapshot
  git clone --depth 1 --filter=blob:none --sparse https://github.com/truenas/apps.git /tmp/truenas-apps
  git -C /tmp/truenas-apps sparse-checkout set ix-dev/stable ix-dev/community
  commit=$(git -C /tmp/truenas-apps rev-parse HEAD)
  python3 - "$commit" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "/src")
from catalog.snapshot import copy_trains, pin_text
dest = Path("/out/payload/catalog-snapshot")
count = copy_trains(Path("/tmp/truenas-apps"), dest)
if count < 1:
    raise SystemExit("catalog snapshot copied no apps")
Path("/out/payload/catalog-pin").write_text(pin_text(sys.argv[1]))
print("catalog apps %s" % count)
PY
fi
python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "/src")
from catalog.snapshot import drop_secret_content
removed = drop_secret_content(Path("/out/payload/catalog-snapshot"))
print("catalog files dropped for the image scan: %s" % removed)
PY
rm -rf "$ROOT/usr/lib/friday/catalog-snapshot"
cp -a /out/payload/catalog-snapshot "$ROOT/usr/lib/friday/catalog-snapshot"
cp /out/payload/catalog-pin "$ROOT/usr/lib/friday/catalog-pin"
if [ -e "$ROOT/usr/lib/friday/catalog-snapshot/ix-dev/enterprise" ] \
  || [ -e "$ROOT/usr/lib/friday/catalog-snapshot/ix-dev/dev" ] \
  || [ -e "$ROOT/usr/lib/friday/catalog-snapshot/ix-dev/test" ]; then
  echo "catalog snapshot included a train that stays out" >&2
  exit 1
fi
cp /src/charters/*.md "$ROOT/soul/agents/"
cp /src/charters/full/*.md "$ROOT/soul/agents-full/"
cp /src/soul/SOUL.example.md "$ROOT/soul/SOUL.md"
python3 - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "/src")
from image.disks import FSTAB_INSTALLER, grub_installer, grub_stub
Path("/build/rootfs/etc/fstab").write_text(FSTAB_INSTALLER)
Path("/build/rootfs/boot/grub/grub.cfg").write_text(grub_installer())
Path("/out/work/grub-installer.cfg").write_text(grub_installer())
Path("/out/work/grub-stub.cfg").write_text(grub_stub())
PY
cp /out/work/grub-stub.cfg "$ROOT/tmp/grub-stub.cfg"
printf '%s\ntest-installer\n' "$VERSION" > "$ROOT/etc/friday-release"
printf 'amd64\n' > "$ROOT/etc/friday-arch"
printf 'installer\n' > "$ROOT/etc/friday-role"
printf 'friday\n' > "$ROOT/etc/hostname"
cat > "$ROOT/etc/hosts" <<'EOF'
127.0.0.1 localhost
127.0.1.1 friday
::1 localhost ip6-localhost ip6-loopback
EOF
ln -sfn /usr/share/zoneinfo/UTC "$ROOT/etc/localtime"
printf 'UTC\n' > "$ROOT/etc/timezone"
python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "/src")
from image.logs import shipped
root = Path("/build/rootfs")
for rel, text in shipped().items():
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if path.stat().st_size < 1:
        raise SystemExit("empty log bound: %s" % rel)
PY
rm -f "$ROOT/etc/machine-id" "$ROOT/var/lib/dbus/machine-id"
: > "$ROOT/etc/machine-id"
chmod 644 "$ROOT/etc/machine-id"
rm -f "$ROOT"/etc/ssh/ssh_host_*
chroot "$ROOT" passwd -l root
if ! chroot "$ROOT" id kiosk >/dev/null 2>&1; then
  chroot "$ROOT" useradd --system --create-home --home-dir /var/lib/kiosk --shell /usr/sbin/nologin kiosk
fi
for group in video render input; do
  chroot "$ROOT" getent group "$group" >/dev/null || chroot "$ROOT" groupadd --system "$group"
done
chroot "$ROOT" usermod -aG video,render,input kiosk
rm -rf "$ROOT/var/lib/iwd"
ln -s /var/lib/friday/iwd "$ROOT/var/lib/iwd"
chroot "$ROOT" dpkg-query -W > /out/packages.txt
cp /out/packages.txt "$ROOT/usr/share/doc/friday/packages.txt"
cat > "$ROOT/usr/share/doc/friday/README" <<EOF
Friday ${VERSION} installer.
This stick installs Debian onto slot A of another disk.
Docker Engine is in this image. Friday, the Board, the memory service, Qdrant, Postgres, Ollama, nomic-embed-text, the webhook receiver, and the gateway are packed in this image.
Creating the server on the installed system starts that core on this computer. Nothing is downloaded.
A catalog snapshot, a display kiosk, and Wi-Fi join are in this image. The Board lists names from that snapshot. Catalog install is refused. There is no SSH.
Container logs rotate at 10 MiB, three files. The journal is capped at 256 MiB, and at 64 MiB while it is only in memory.
EOF
cp "$ROOT/etc/os-release" /out/debian-os-release

enable_unit() {
  local unit="$1"
  local src=""
  if [ -e "$ROOT/usr/lib/systemd/system/$unit" ]; then
    src="/usr/lib/systemd/system/$unit"
  elif [ -e "$ROOT/lib/systemd/system/$unit" ]; then
    src="/lib/systemd/system/$unit"
  else
    echo "missing unit $unit" >&2
    return 1
  fi
  mkdir -p "$ROOT/etc/systemd/system/multi-user.target.wants"
  ln -sfn "$src" "$ROOT/etc/systemd/system/multi-user.target.wants/$unit"
}
if ! chroot "$ROOT" systemctl enable systemd-networkd.service systemd-resolved.service friday-setup.service; then
  enable_unit systemd-networkd.service
  enable_unit systemd-resolved.service
  enable_unit friday-setup.service
fi
chroot "$ROOT" systemctl enable systemd-timesyncd.service || enable_unit systemd-timesyncd.service || true
chroot "$ROOT" systemctl enable docker.service || enable_unit docker.service || true
if ! chroot "$ROOT" systemctl enable friday-kiosk.service; then
  mkdir -p "$ROOT/etc/systemd/system/multi-user.target.wants"
  ln -sfn /etc/systemd/system/friday-kiosk.service \
    "$ROOT/etc/systemd/system/multi-user.target.wants/friday-kiosk.service"
fi
ln -sfn /dev/null "$ROOT/etc/systemd/system/getty@tty1.service"
ln -sfn /dev/null "$ROOT/etc/systemd/system/serial-getty@ttyS0.service"
for unit in apt-daily.timer apt-daily-upgrade.timer; do
  if [ -e "$ROOT/usr/lib/systemd/system/$unit" ] || [ -e "$ROOT/lib/systemd/system/$unit" ]; then
    ln -sfn /dev/null "$ROOT/etc/systemd/system/$unit"
  fi
done
ln -sfn /run/systemd/resolve/stub-resolv.conf "$ROOT/etc/resolv.conf"

MODDIR="$ROOT/usr/lib/grub/x86_64-efi"
mods=()
for mod in part_gpt part_msdos fat ext2 normal linux configfile search search_fs_uuid search_label search_fs_file all_video gfxterm echo test reboot serial chain ls cat boot gzio halt efi_gop video video_bochs video_cirrus probe; do
  if [ -f "$MODDIR/$mod.mod" ]; then
    mods+=("$mod")
  fi
done
for required in part_gpt ext2 fat linux normal configfile search search_label search_fs_file echo serial; do
  if [ ! -f "$MODDIR/$required.mod" ]; then
    echo "missing grub module $required" >&2
    exit 1
  fi
done
chroot "$ROOT" grub-mkimage -d /usr/lib/grub/x86_64-efi -O x86_64-efi \
  -c /tmp/grub-stub.cfg -o /usr/lib/friday/BOOTX64.EFI -p /EFI/BOOT "${mods[@]}"
python3 - <<'PY'
from pathlib import Path
blob = Path("/build/rootfs/usr/lib/friday/BOOTX64.EFI").read_bytes()[:2]
if blob != b"MZ":
    raise SystemExit("BOOTX64.EFI is not a PE binary")
PY
rm -f "$ROOT/tmp/grub-stub.cfg"

kernel=$(find "$ROOT/boot" -maxdepth 1 -type f -name 'vmlinuz-*' | head -n 1)
initrd=$(find "$ROOT/boot" -maxdepth 1 -type f -name 'initrd.img-*' | head -n 1)
if [ -z "$kernel" ] || [ -z "$initrd" ]; then
  echo "kernel or initrd missing" >&2
  exit 1
fi
case "$(basename "$kernel")" in
  *amd64*) ;;
  *) echo "kernel is not amd64: $kernel" >&2; exit 1 ;;
esac
ln -sfn "$(basename "$kernel")" "$ROOT/boot/vmlinuz"
ln -sfn "$(basename "$initrd")" "$ROOT/boot/initrd.img"
if chroot "$ROOT" dpkg-query -W -f '${Status}\n' openssh-server 2>/dev/null | grep -q 'install ok installed'; then
  echo "openssh-server is installed" >&2
  exit 1
fi

stage images
load_images

stage pack
cleanup_binds
if mountpoint -q "$ROOT/proc" || mountpoint -q "$ROOT/dev" || mountpoint -q "$ROOT/sys"; then
  echo "a bind mount is still up" >&2
  exit 1
fi
find "$ROOT" -xdev \( -type s -o -type p \) -delete
rm -rf "$ROOT/var/lib/apt/lists/"* "$ROOT/var/cache/apt/archives/"*.deb \
  "$ROOT/tmp/"* "$ROOT/var/tmp/"* "$ROOT/root/.bash_history" || true
find "$ROOT/var/log" -type f -delete || true
rm -f "$ROOT/etc/machine-id" "$ROOT/var/lib/dbus/machine-id"
: > "$ROOT/etc/machine-id"
chmod 644 "$ROOT/etc/machine-id"

stage scan
for required in \
  usr/lib/friday/image/wifi.py \
  usr/lib/friday/image/kiosk.py \
  usr/lib/friday/image/logs.py \
  usr/lib/friday/image/mesh.py \
  etc/docker/daemon.json \
  etc/systemd/journald.conf.d/friday.conf \
  etc/friday-log-ceiling \
  etc/systemd/system/friday-kiosk.service \
  usr/lib/friday/catalog-pin \
  usr/lib/friday/wires/jellyfin.yml \
  usr/lib/friday/catalog/PIN \
  usr/lib/friday/catalog/allowlist.py \
  usr/lib/friday/helm/Chart.yaml \
  usr/lib/friday/helm/templates/workloads.yaml \
  usr/lib/friday/helm/templates/pvc.yaml
do
  if [ ! -s "$ROOT/$required" ]; then
    echo "missing $required" >&2
    exit 1
  fi
done
if [ ! -d "$ROOT/usr/lib/friday/catalog-snapshot/ix-dev/stable" ] \
  && [ ! -d "$ROOT/usr/lib/friday/catalog-snapshot/ix-dev/community" ]; then
  echo "catalog snapshot is missing" >&2
  exit 1
fi
python3 /src/image/scan.py "$ROOT"

rm -f /out/work/efi.img
truncate -s 512M /out/work/efi.img
mkfs.vfat -F 32 -n FRIDAYEFI /out/work/efi.img
mmd -i /out/work/efi.img ::/EFI
mmd -i /out/work/efi.img ::/EFI/BOOT
mcopy -i /out/work/efi.img "$ROOT/usr/lib/friday/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI
mcopy -i /out/work/efi.img /out/work/grub-installer.cfg ::/EFI/BOOT/grub.cfg
fsck.vfat -n /out/work/efi.img
listing=$(mdir -i /out/work/efi.img ::/EFI/BOOT)
printf '%s\n' "$listing" | grep -q 'BOOTX64' || { printf '%s\n' "$listing" >&2; echo "ESP is missing BOOTX64.EFI" >&2; exit 1; }

sync
umount "$ROOT"
if mountpoint -q "$ROOT"; then
  echo "root is still mounted" >&2
  exit 1
fi
detach_loops "$ROOTIMG"
sync
set +e
e2fsck -fy "$ROOTIMG"
rc=$?
set -e
if [ "$rc" -gt 1 ]; then
  echo "e2fsck failed: $rc" >&2
  exit 1
fi
mount -o loop,ro "$ROOTIMG" "$ROOT"
assert_payload_present
umount "$ROOT"
detach_loops "$ROOTIMG"
resize2fs -M "$ROOTIMG"
blocks=$(dumpe2fs -h "$ROOTIMG" | awk '/^Block count:/{print $3}')
bsize=$(dumpe2fs -h "$ROOTIMG" | awk '/^Block size:/{print $3}')
fs_bytes=$((blocks * bsize))
root_bytes=$(((fs_bytes + 768 * 1024 * 1024 + 1048575) / 1048576 * 1048576))
root_mib=$((root_bytes / 1048576))
resize2fs "$ROOTIMG" "${root_mib}M"
truncate -s "${root_mib}M" "$ROOTIMG"
sync
set +e
e2fsck -fy "$ROOTIMG"
rc=$?
set -e
if [ "$rc" -gt 1 ]; then
  echo "e2fsck after resize failed: $rc" >&2
  exit 1
fi

if [ "$root_mib" -gt $((15 * 1024)) ]; then
  echo "root is ${root_mib} MiB and does not fit the 16 GiB system slot" >&2
  exit 1
fi
IMG="friday-${VERSION}-usb.img"
disk_mib=$((1 + 512 + root_mib + 1))
end_mib=$((513 + root_mib))
echo "root partition ${root_mib} MiB, disk ${disk_mib} MiB"
rm -f "/out/work/${IMG}"
truncate -s "${disk_mib}M" "/out/work/${IMG}"
parted -s "/out/work/${IMG}" mklabel gpt
parted -s "/out/work/${IMG}" mkpart friday-efi fat32 1MiB 513MiB
parted -s "/out/work/${IMG}" set 1 esp on
parted -s "/out/work/${IMG}" mkpart friday-installer ext4 513MiB "${end_mib}MiB"
parted -m "/out/work/${IMG}" unit B print > /out/work/disk-parted.txt
python3 - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "/src")
from image.disks import parse_parted
rows = parse_parted(Path("/out/work/disk-parted.txt").read_text())
if len(rows) != 2 or rows[0]["end"] >= rows[1]["start"]:
    raise SystemExit("disk partitions overlap")
if "esp" not in rows[0]["flags"]:
    raise SystemExit("efi partition has no esp flag")
Path("/out/work/disk-spans").write_text(
    "%s %s\n%s %s\n" % (rows[0]["start"], rows[0]["size"], rows[1]["start"], rows[1]["size"])
)
PY
{
  read -r efi_start efi_size
  read -r root_start root_size
} < /out/work/disk-spans
efi_file=$(stat -c '%s' /out/work/efi.img)
root_file=$(stat -c '%s' "$ROOTIMG")
if [ "$efi_size" != "$efi_file" ] || [ "$root_size" != "$root_file" ]; then
  echo "partition size does not match the filesystem image (efi $efi_size/$efi_file root $root_size/$root_file)" >&2
  exit 1
fi
dd if=/out/work/efi.img of="/out/work/${IMG}" bs=1M seek="$((efi_start / 1048576))" conv=notrunc,sparse status=none
dd if="$ROOTIMG" of="/out/work/${IMG}" bs=1M seek="$((root_start / 1048576))" conv=notrunc,sparse status=none
sync

label=$(debugfs -R "cat etc/friday-role" "$ROOTIMG")
printf '%s' "$label" | grep -qx 'installer'
debugfs -R "stat boot/vmlinuz" "$ROOTIMG" >/out/work/vmlinuz-stat.txt
grep -q 'Type: symlink' /out/work/vmlinuz-stat.txt

stage lab
make_lab

stage compress
xz -T0 -6 -c "/out/work/${IMG}" > "/out/${IMG}.xz"
size=$(stat -c '%s' "/out/${IMG}.xz")
if [ "$size" -gt 1900000000 ]; then
  printf 'compressed image is %s bytes, over the GitHub release limit\n' "$size" | tee /out/github-release-blocked >&2
else
  rm -f /out/github-release-blocked
fi
(
  cd /out
  sha256sum "${IMG}.xz" > SHA256SUMS
)
img_hash=$(sha256sum "/out/work/${IMG}" | awk '{print $1}')
printf '%s  %s\n' "$img_hash" "$IMG" >> /out/SHA256SUMS
printf '%s\n' "$IMG" > /out/IMAGE-NAME
stage done
echo "image bytes xz=${size}"
