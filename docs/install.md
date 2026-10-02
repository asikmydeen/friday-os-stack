# Flash the Friday 0.0.1 test installer

The appliance image, from the build through first boot and the setup page, is in [setup.md](setup.md). This page is the published v0.0.1 test installer.

v0.0.1 is a disk image you can boot. It is the installer, not the finished appliance. The stick copies Debian onto another disk and then shows a setup screen. Friday does not speak in this image.

Download it from the [v0.0.1 release](https://github.com/asikmydeen/friday-os-stack/releases/tag/v0.0.1). The image is not a file in the git tree.

The source tree's image build packs Docker Engine, Friday, the Board, the memory service, Qdrant, Postgres, Ollama, and `nomic-embed-text`, and it refuses to finish without that payload. It also packs the webhook receiver, the gateway, a catalog snapshot, a display kiosk, and Wi-Fi join. v0.0.1, the file on the release page, does not contain them. A later local image was booted under QEMU. Its serial log printed “The core on this computer was started. Nothing was downloaded.” and did not say the webhook receiver, the gateway, the catalog snapshot, the kiosk, or Wi-Fi join were omitted. That boot had no graphics device and no wireless adapter, so the kiosk and the Wi-Fi join did not run. The setup screen still said the embed check was not checked, and setup was not finished. That compressed file is over the GitHub release limit, so it is not on the release page. A later local image also packs the messaging door and the inbound MCP listener on an internal doors network under profile reach, with no host port. A QEMU boot of that image printed “The core on this computer was started.” The serial capture ends on that line. It did not say those five pieces were omitted, and it did not report that profile reach had started. Creating the server does not start that profile. The setup screen still said the embed check was not checked, and setup was not finished. The boot had no graphics device and no wireless adapter. That compressed file is also over the GitHub release limit, so v0.0.1 remains the file on the release page. A later local image also packs the browser session on an internal browser network under the same profile, with no host port. A QEMU boot of that image printed “The core on this computer was started. Nothing was downloaded.” It did not say those five pieces were omitted, and it did not report that profile reach had started. The setup screen still said the embed check was not checked, and setup was not finished. The boot had no graphics device and no wireless adapter. That compressed file is also over the GitHub release limit. A later local image also packs outbound MCP on an internal outbound network under the same profile, with no host port. A QEMU boot of that image printed “The core on this computer was started. Nothing was downloaded.” It did not report that profile reach had started. The setup screen still said the embed check was not checked, and setup was not finished. The boot had no graphics device and no wireless adapter. That compressed file is also over the GitHub release limit.

A later start records `Embed: nomic-embed-text, 768` only when that start returns a vector of 768 numbers from `nomic-embed-text`. A check that returns nothing leaves the line at not checked. The boots above did not write that flag. This change has not been booted.

The image build writes Docker log rotation at 10 MiB with three files, and a journal cap of 256 MiB when the journal is stored and 64 MiB while it is only in memory. It also writes those numbers, and the 16 GiB data-partition floor, to `etc/friday-log-ceiling`. That file does not measure free space and does not delete a log. This build has not been booted. v0.0.1 does not contain those files.

## What you are flashing

The tested machine is one x86_64 computer that boots UEFI, with at least 8 GB of RAM and an internal disk of at least 64 GB. Secure Boot has to be off. This GRUB is not signed by Microsoft, so a machine with Secure Boot left on will not boot the stick. Legacy BIOS and CSM are not targets. An Apple Silicon Mac does not boot this image natively.

The stick is only the installer. It does not become the system disk. The internal disk is named later, on the Friday machine, after the stick has booted.

This image contains Debian and the installer. The release page records the Debian version and the package list this artifact was built from. It does not contain Friday, the Board, the memory service, Qdrant, Postgres, Ollama, or the embed model. Docker Engine is not in this test image. There is no SSH, no display manager, and no full-screen browser. Catalog install is refused.

The screen you get is a text console. The same rules are also served at `http://127.0.0.1:8080` on that machine. That page is not the Node Board. It says the Board is not in this image.

Wired DHCP is the link this image can bring up. A network card that needs non-free firmware will not link. Saving a Wi-Fi name and password stores them and does not join Wi-Fi. Choosing "create the server" records the confirmation. Nothing is started and nothing is downloaded. Setup cannot finish, because the embed model is not in the image, so the provisioning token stays and `/provision` does not return 404. The Board password stays on the screen.

Two machines started from this image mint different ids and secrets on the installed system. The published image has an empty machine id, no SSH host keys, no default password, and no application secrets. A power loss after the secrets exist does not mint a second set. This release was not tried on two physical machines.

There is no detached signature in this test release. Check the SHA-256 before you write the stick. The checksum is not a signature.

This image was booted once under emulation to the text screen. The stick was marked as the installer, and a second disk was left untouched. It has not been tried on two physical machines.

## Verify, then decompress

The release has two files:

- `friday-0.0.1-usb.img.xz` is the download.
- `SHA256SUMS` lists that file and the uncompressed `friday-0.0.1-usb.img`.

Check the download before you decompress it. On a Mac:

```bash
grep 'friday-0.0.1-usb.img.xz$' SHA256SUMS | shasum -a 256 -c -
```

On Linux:

```bash
grep 'friday-0.0.1-usb.img.xz$' SHA256SUMS | sha256sum -c -
```

The line has to print `OK`. Then decompress. Flashing the `.xz` file itself will not boot.

```bash
xz -dk friday-0.0.1-usb.img.xz
```

Check the uncompressed image against the second line. On a Mac:

```bash
grep 'friday-0.0.1-usb.img$' SHA256SUMS | shasum -a 256 -c -
```

On Linux:

```bash
grep 'friday-0.0.1-usb.img$' SHA256SUMS | sha256sum -c -
```

Write the `.img` file, not the `.xz` file.

## Write the stick

Find the USB stick first. Write only to that stick. The command below erases the device you name.

On a Mac, the internal disk is `disk0`. Do not use `disk0` or `rdisk0`.

```bash
diskutil list
diskutil unmountDisk /dev/diskN
sudo dd if=friday-0.0.1-usb.img of=/dev/rdiskN bs=4m
```

Replace `diskN` with the stick from `diskutil list`. macOS `dd` does not print progress. Press Ctrl-T to see how far it has written. When it returns:

```bash
sync
diskutil eject /dev/diskN
```

On Linux, list disks and use the stick, not the disk the computer booted from:

```bash
lsblk
sudo dd if=friday-0.0.1-usb.img of=/dev/sdX bs=4M conv=fsync status=progress
sync
```

Replace `sdX` with the stick. `of=` is the whole disk, such as `/dev/sdb`, not a partition such as `/dev/sdb1`.

## Boot and name the internal disk

Open the machine's boot menu and choose the USB stick in UEFI mode. Turn Secure Boot off before that boot.

The screen says `Friday 0.0.1 test installer` and lists every disk it can see, with its size. The stick is marked `installer`. Type the kernel name of the internal disk exactly as listed: `sda`, `vda`, or `nvme0n1`. Do not type `/dev/sda`, and do not type a partition name such as `sda1` or `nvme0n1p1`.

The installer asks for that same name a second time. Only the second, matching name erases the disk. A different second name erases nothing. The stick is never an accepted answer. A disk that cannot hold the layout is refused. If the installer cannot tell which disk is the stick, it refuses every disk.

The layout it writes is an EFI partition of 512 MiB (partition name `friday-efi`), system slot A of 16 GiB (`friday-a`), system slot B of 16 GiB (`friday-b`, empty), and a data partition (`friday-data`) that fills the rest. The data partition has to be at least 16 GiB, and the disk has to be at least 64 GB in decimal bytes. A disk sold as 64 GB is usually about 64,000,000,000 bytes and still fits. Files you care about go on the data partition, not on slot A or slot B.

When the copy finishes, remove the stick and type `reboot`. The installed bootloader boots slot A. Slot B is recorded as the later update target. This version does not switch slots. If the copy stops with an error, the disk you named may already be erased.

## What the installed screen can and cannot do

There is no SSH. Use the keyboard and monitor on that computer.

The setup screen asks for a link, a server confirmation, a name, a timezone, a model endpoint, and the Board password. The model endpoint is any OpenAI-compatible URL. This screen names no vendor. Chat stays off until that endpoint returns a real, non-empty reply, and the local embed check returns a 768-dimension vector from `nomic-embed-text`. A different model id is refused, including when that vector is also 768 long. A reply with no model id is refused. A stored yes does not skip the check. This image has no embed model, so the check cannot pass and setup stays open.

The page cannot install a catalog app, change a grant, or read owner memory. Replacing a lost Board password is a prompt on the text console, after setup has completed. This image does not complete setup, so that prompt is not available yet.

## Try it in a virtual machine

Use two disks. The first is the USB image. The second is a new file of at least 64 GB. The installer must refuse to erase the stick, so a one-disk VM is the wrong test. Do not point the emulator at a real disk.

Copy the OVMF variables file before you start. The code file stays read-only. Homebrew often installs the code at `/opt/homebrew/share/qemu/edk2-x86_64-code.fd` and the variables at `edk2-i386-vars.fd`. Debian often uses `/usr/share/OVMF/OVMF_CODE_4M.fd`. Use the firmware that does not turn Secure Boot on.

```bash
cp /opt/homebrew/share/qemu/edk2-i386-vars.fd vars.fd
truncate -s 64G target.img
qemu-system-x86_64 \
  -machine q35 \
  -m 8192 \
  -drive if=pflash,format=raw,readonly=on,file=/opt/homebrew/share/qemu/edk2-x86_64-code.fd \
  -drive if=pflash,format=raw,file=vars.fd \
  -drive if=none,id=stick,format=raw,file=friday-0.0.1-usb.img \
  -device qemu-xhci,id=xhci \
  -device usb-storage,bus=xhci.0,drive=stick,bootindex=0 \
  -drive if=virtio,format=raw,file=target.img \
  -serial file:serial.log \
  -display cocoa
```

Leave the serial log in a file. Do not attach serial to the terminal, or the window loses the keyboard. Do not type a disk name unless both drives are files you created for this VM. The installer erases the disk whose name you type twice.
