#!/bin/bash
# Runs inside a privileged linux/amd64 Debian container. Do not run this on the Mac.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

stage() { printf '%s\n' "$1" > /out/stage; echo "== $1 =="; }

if [ "$(uname -m)" != "x86_64" ]; then
  echo "builder is $(uname -m), want x86_64" >&2
  exit 1
fi

ROOT=/build/rootfs
ROOTIMG=/out/work/root.img
mkdir -p /out/work /out/scan /build
stage tools
apt-get update
apt-get install -y --no-install-recommends \
  debootstrap parted e2fsprogs dosfstools mtools python3 \
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
if [ ! -f /out/work/stamp-debootstrap ]; then
  rm -f "$ROOTIMG"
  truncate -s 8G "$ROOTIMG"
  mkfs.ext4 -F -L friday-installer "$ROOTIMG"
fi
mkdir -p "$ROOT"
if ! mountpoint -q "$ROOT"; then
  mount -o loop "$ROOTIMG" "$ROOT"
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

PACKAGES="linux-image-amd64 systemd systemd-sysv udev dbus systemd-resolved systemd-timesyncd kmod python3 parted gdisk e2fsprogs dosfstools rsync grub-efi-amd64-bin ca-certificates tzdata iproute2 firmware-linux-free"
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
for name in __init__.py disks.py install.py setup.py provision.py console.py main.py; do
  cp "/src/image/$name" "$ROOT/usr/lib/friday/image/$name"
done
cp /src/image/assets/friday-setup.service "$ROOT/etc/systemd/system/friday-setup.service"
cp /src/image/assets/20-wired.network "$ROOT/etc/systemd/network/20-wired.network"
cp /src/image/assets/friday-omitted "$ROOT/etc/friday-omitted"
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
rm -f "$ROOT/etc/machine-id" "$ROOT/var/lib/dbus/machine-id"
: > "$ROOT/etc/machine-id"
chmod 644 "$ROOT/etc/machine-id"
rm -f "$ROOT"/etc/ssh/ssh_host_*
chroot "$ROOT" passwd -l root
chroot "$ROOT" dpkg-query -W > /out/packages.txt
cp /out/packages.txt "$ROOT/usr/share/doc/friday/packages.txt"
cat > "$ROOT/usr/share/doc/friday/README" <<EOF
Friday ${VERSION} test installer.
This stick installs Debian onto slot A of another disk.
Friday, the Board, and the core containers are not in this image.
Docker Engine is not in this image. Catalog install is refused. There is no SSH.
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

umount "$ROOT"
set +e
e2fsck -fy "$ROOTIMG"
rc=$?
set -e
if [ "$rc" -gt 1 ]; then
  echo "e2fsck failed: $rc" >&2
  exit 1
fi
resize2fs -M "$ROOTIMG"
blocks=$(dumpe2fs -h "$ROOTIMG" | awk '/^Block count:/{print $3}')
bsize=$(dumpe2fs -h "$ROOTIMG" | awk '/^Block size:/{print $3}')
fs_bytes=$((blocks * bsize))
root_bytes=$(((fs_bytes + 768 * 1024 * 1024 + 1048575) / 1048576 * 1048576))
root_mib=$((root_bytes / 1048576))
resize2fs "$ROOTIMG" "${root_mib}M"
truncate -s "${root_mib}M" "$ROOTIMG"
e2fsck -fn "$ROOTIMG"

disk_mib=$((1 + 512 + root_mib + 1))
end_mib=$((513 + root_mib))
echo "root partition ${root_mib} MiB, disk ${disk_mib} MiB"
rm -f /out/work/friday-0.0.1-usb.img
truncate -s "${disk_mib}M" /out/work/friday-0.0.1-usb.img
parted -s /out/work/friday-0.0.1-usb.img mklabel gpt
parted -s /out/work/friday-0.0.1-usb.img mkpart friday-efi fat32 1MiB 513MiB
parted -s /out/work/friday-0.0.1-usb.img set 1 esp on
parted -s /out/work/friday-0.0.1-usb.img mkpart friday-installer ext4 513MiB "${end_mib}MiB"
parted -m /out/work/friday-0.0.1-usb.img unit B print > /out/work/disk-parted.txt
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
dd if=/out/work/efi.img of=/out/work/friday-0.0.1-usb.img bs=1M seek="$((efi_start / 1048576))" conv=notrunc,sparse status=none
dd if="$ROOTIMG" of=/out/work/friday-0.0.1-usb.img bs=1M seek="$((root_start / 1048576))" conv=notrunc,sparse status=none
sync

label=$(debugfs -R "cat etc/friday-role" "$ROOTIMG")
printf '%s' "$label" | grep -qx 'installer'
debugfs -R "stat boot/vmlinuz" "$ROOTIMG" >/out/work/vmlinuz-stat.txt
grep -q 'Type: symlink' /out/work/vmlinuz-stat.txt

stage compress
xz -T0 -6 -c /out/work/friday-0.0.1-usb.img > /out/friday-0.0.1-usb.img.xz
size=$(stat -c '%s' /out/friday-0.0.1-usb.img.xz)
if [ "$size" -gt 1900000000 ]; then
  echo "compressed image is ${size} bytes, over the 2 GB release limit" >&2
  exit 1
fi
(
  cd /out
  sha256sum friday-0.0.1-usb.img.xz > SHA256SUMS
)
img_hash=$(sha256sum /out/work/friday-0.0.1-usb.img | awk '{print $1}')
printf '%s  friday-0.0.1-usb.img\n' "$img_hash" >> /out/SHA256SUMS
stage done
echo "image bytes xz=${size}"
