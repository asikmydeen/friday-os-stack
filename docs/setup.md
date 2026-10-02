# Install and set up Friday

This is the path from an empty computer to a Friday appliance. You build a disk image, write it to a USB stick, boot that stick, copy Friday onto an internal disk, and finish setup on a monitor attached to that computer.

The appliance image is Friday 0.0.2. It contains Debian, Docker Engine, Friday, the Board, the memory service, Qdrant, Postgres, Ollama, and the embed model `nomic-embed-text`. Creating the server starts that core on this computer. The webhook receiver and the gateway start with it. A catalog snapshot, a display kiosk, and Wi-Fi join are in the image. Nothing is downloaded during that start.

There is no SSH. Use the keyboard and the monitor on the Friday computer.

Catalog install stays closed. The Board can list names from the catalog snapshot. It does not install them.

## Which image

Two images exist. They are not interchangeable.

**v0.0.1** is the file on the [release page](https://github.com/asikmydeen/friday-os-stack/releases/tag/v0.0.1). It is a test installer. It copies Debian onto a disk and shows a setup screen. Friday, the Board, Docker, and the embed model are absent, so setup cannot finish. The flash steps for that file are in [install.md](install.md).

**0.0.2** is the appliance this page installs. The repository builds it. The compressed file is over the GitHub release limit, so it is not attached to a release. You build it, check the checksum the build writes, and flash that file.

An earlier local image was booted under QEMU far enough to print “The core on this computer was started. Nothing was downloaded.” That boot did not finish setup. A boot of this 0.0.2 image on two physical machines is still open. The steps below are what the installer and the setup page do.

## The computer

The appliance boots on x86_64 UEFI. Secure Boot has to be off. This GRUB is not signed by Microsoft, so a machine with Secure Boot left on will not boot the stick. Legacy BIOS and CSM are outside this installer. An Apple Silicon Mac does not boot the image natively. It can build the image when Docker can run a privileged `linux/amd64` container.

The tested target has at least 8 GB of RAM and an internal disk of at least 64 GB. The installer warns when the machine reports under 8 GB. The stick is only the installer. It does not become the system disk.

You also need:

- A monitor and a keyboard on the Friday computer. The kiosk opens when a graphics device is present.
- A USB stick big enough for the uncompressed image. The raw image is about 11 GB, so use a stick larger than that.
- A network route before setup can finish. A cable with DHCP is the link the installer brings up reliably. A Wi-Fi name and password can be stored, and this image tries to join that network.
- An OpenAI-compatible chat endpoint and an API key. The image does not include a chat-sized model. It does include `nomic-embed-text` for the local embed check.
- On the machine that builds the image: Docker, a checkout of this repository, and room under `/tmp`. The build keeps the raw image, the compressed file, and several root-filesystem copies. Plan on at least 60 GB free.

## Build the image

From the repository root:

```bash
git clone https://github.com/asikmydeen/friday-os-stack
cd friday-os-stack
scripts/fetch-core.sh
image/build.sh
```

`scripts/fetch-core.sh` packs the core images and the embed weights. `image/build.sh` builds the installer inside a privileged Debian container and writes it under `/tmp/friday-image`. Run each command once and wait until the build prints `== done ==`.

When it finishes, these files are the ones to keep:

| File | Role |
| --- | --- |
| `/tmp/friday-image/friday-0.0.2-usb.img.xz` | Compressed installer. This is the file you copy to the computer that writes the stick. |
| `/tmp/friday-image/work/friday-0.0.2-usb.img` | Uncompressed disk image. This is the file you write to the stick. |
| `/tmp/friday-image/SHA256SUMS` | Checksums for both files, written when the build finishes. |

The build also writes `/tmp/friday-image/github-release-blocked` when the compressed file is over the GitHub release limit. That note means the file stays on this computer. There is no detached signature. The checksum is the check you have.

## Check the files

Check both files against `SHA256SUMS` before you write a stick. On a Mac:

```bash
cd /tmp/friday-image
grep 'friday-0.0.2-usb.img.xz$' SHA256SUMS | shasum -a 256 -c -
grep 'friday-0.0.2-usb.img$' SHA256SUMS | shasum -a 256 -c -
```

On Linux, use `sha256sum -c -` in place of `shasum -a 256 -c -`. Each line has to print `OK`.

If you moved only the `.xz` file, decompress it first and check the raw image with the second line of `SHA256SUMS`. Flashing the `.xz` file itself will not boot.

```bash
xz -dk friday-0.0.2-usb.img.xz
```

## Write the stick

Find the USB stick and write only to that stick. The command erases the device you name.

On a Mac, the internal disk is `disk0`. Leave `disk0` and `rdisk0` alone.

```bash
diskutil list
diskutil unmountDisk /dev/diskN
sudo dd if=friday-0.0.2-usb.img of=/dev/rdiskN bs=4m
sync
diskutil eject /dev/diskN
```

Replace `diskN` with the stick from `diskutil list`. macOS `dd` does not print progress. Press Ctrl-T to see how far it has written.

On Linux, list disks and use the stick, not the disk the computer booted from:

```bash
lsblk
sudo dd if=friday-0.0.2-usb.img of=/dev/sdX bs=4M conv=fsync status=progress
sync
```

Replace `sdX` with the stick. `of=` is the whole disk, such as `/dev/sdb`, not a partition such as `/dev/sdb1`.

## Boot the stick and name the internal disk

Open the machine's boot menu and choose the USB stick in UEFI mode. Turn Secure Boot off before that boot.

The screen says `Friday 0.0.2 test installer` and lists every disk it can see, with its size. The stick is marked `installer`. Type the kernel name of the internal disk exactly as listed: `sda`, `vda`, or `nvme0n1`. Type the name alone. A path such as `/dev/sda`, and a partition name such as `sda1` or `nvme0n1p1`, are refused.

The installer asks for that same name a second time. Only the second, matching name erases the disk. A different second name erases nothing. The stick is never an accepted answer. A disk that cannot hold the layout is refused. If the installer cannot tell which disk is the stick, it refuses every disk.

The layout it writes:

| Partition | Size | Name |
| --- | --- | --- |
| EFI | 512 MiB | `friday-efi` |
| System slot A | 16 GiB | `friday-a` |
| System slot B | 16 GiB, empty | `friday-b` |
| Data | the rest, at least 16 GiB | `friday-data` |

The disk has to be at least 64 GB in decimal bytes. A disk sold as 64 GB is usually about 64,000,000,000 bytes and still fits. Files you care about go on the data partition. Slot B is the later update target. This version does not switch slots.

When the copy finishes, the screen says to remove the stick and type `reboot`. The installed bootloader boots slot A. If the copy stops with an error, the disk you named may already be erased.

Two machines started from this image mint different ids and secrets. The image has an empty machine id, no SSH host keys, no default password, and no application secrets. A power loss after the secrets exist does not mint a second set.

## First boot

Remove the stick before the installed system boots. Connect a cable if you have one. The data partition has to be mounted. If it is not, the screen says secrets were not created and setup stops.

The setup service listens on `127.0.0.1:8080` on that computer. When a graphics device is present, the kiosk opens a full-screen browser on the setup page. The page heading is **Friday setup**. The page says it is only on this computer, and that catalog install stays closed.

The status block on that page shows two values until setup is finished. Write both down before you press **Finish setup**. They leave the screen when setup completes.

- **Board password.** This is the password for the Board. You type it back later on the same page to confirm you saved it.
- **Character apply token.** The Board asks for this when you apply a character change. It is a different value from the Board password.

## The setup page, in order

Finish setup stays refused until every required line below is done and the computer has a network route. Mesh is optional. Leaving the mesh unset is a complete install.

The page shows a reason when a step is refused. Fix that step and submit it again. A stored “yes” does not skip the model check or the embed check.

### 1. Link

Press **Use the cable** when Ethernet is connected.

For Wi-Fi, type the network name and the password and press **Store Wi-Fi**. The password is stored and is not shown again. This image then tries to join that network. The status line says `Wi-Fi: joined <name>` when the join worked. When it did not, the cable is the link setup can finish on.

The link line says `no route` until a path to the network exists. **Finish setup** refuses with `no_route` while that is true.

### 2. Mesh

Choose this before **Create the server on this computer**. Pressing that server button again, before setup is finished, applies a mesh choice you made later. After setup is finished, the mesh choice stays as it was.

Leave the section unset, or press **This computer only**, to keep the Board on this computer. That is a complete install. The status line says `Mesh: this computer only`.

**Join an existing mesh.** This computer runs the Tailscale client. Headscale stays where it already runs. Type the control URL and a pre-auth key and press **Join an existing mesh**. The URL is `http` or `https`, with a host, and with no user name, password, query, or fragment. The key is stored mode 0600 and is not shown on the page. The status line says `Mesh: joining <url>`.

**Create the mesh on this computer.** This computer runs Headscale, and a client that joins it. Type the control URL other devices will use and press **Create the mesh on this computer**. That URL has to be reachable from those devices, such as `http://192.168.1.20:8443`. It needs a port. The port cannot be 8080, 11434, 5432, 6333, 8090, or 6334, because those belong to the Board, Ollama, Postgres, Qdrant, and the gateway. A loopback address, `localhost`, and a name under `friday.mesh` are refused. The status line says `Mesh: this computer. Other devices use <url>`.

The phone key and the laptop key appear after the server starts, and only while setup is still open. Each key works once and expires after seven days. Copy them before you finish. This computer's own key is not shown. If you finished without copying them, they are still on this computer, mode 0600:

- `/var/lib/friday/headscale/phone.key`
- `/var/lib/friday/headscale/laptop.key`

The more detailed mesh rules are in [headscale.md](headscale.md).

### 3. Create the server

Press **Create the server on this computer**.

On success the status says `The core on this computer was started. Nothing was downloaded.` and `Server: confirmed`. That start brings up Friday, the Board, the memory service, Qdrant, Postgres, Ollama, `nomic-embed-text`, the webhook receiver, and the gateway, from images already in the file. It does not start the messaging door, the inbound MCP listener, the browser session, or outbound MCP. Those sit under profile `reach` and stay off.

If the status says `The core did not start. Nothing was downloaded.`, the detail line names the reason. Creating the server again is safe. It starts the same core again.

When you created a mesh, wait until the phone key and the laptop key are on the page before you leave this step.

### 4. Name

Type a display name and press **Save name**. The name can be up to 80 characters. It cannot start or end with a space.

### 5. Timezone

Type an IANA timezone that exists on this computer, such as `America/Los_Angeles` or `UTC`, and press **Save timezone**.

### 6. Model

Type the chat endpoint and press **Check the model**.

- **Base URL.** `http` or `https`, with a host, and with no user name, password, query, or fragment. The check calls that URL plus `/v1/chat/completions`, unless the URL already ends in `/v1` or `/chat/completions`.
- **Fast model.** The model name the endpoint expects.
- **Think model.** Optional. Leave it blank to skip it.
- **API key.** Required. It is stored on this computer and is not shown again.

The step passes when the endpoint returns a real, non-empty reply. The status line then says `Model: reply received`. An empty reply, a refusal, or a missing route leaves it at `Model: not checked`.

### 7. Board password

Type the Board password from the status block into both fields and press **I saved the password**. The two entries have to match the password on the screen. The status line then says `Password: confirmed`.

### 8. Finish

Press **Finish setup**.

This checks the link, the server, the name, the timezone, the model reply, and the password confirmation again. It also asks the local embed model for a vector. Success records `Embed: nomic-embed-text, 768`. A missing vector, a short vector, or a different model id refuses the finish, and setup stays open.

On success the provision page closes. The Board password and the character apply token leave the status screen. The kiosk opens the Board at `http://127.0.0.1:8080/`.

## Open the Board

On the Friday computer the Board is `http://127.0.0.1:8080/`. Sign in with the Board password you wrote down.

The messaging door, the MCP listener, the browser session, and outbound MCP are still off. Catalog install stays closed. Chat on the Board cannot install an app, change the mesh, or approve a send, a payment, a delete, or a publish.

## Open the Board from a phone or a laptop

This works after you joined a mesh or created one. The Board process stays on `127.0.0.1:8080`. The client on the Friday computer publishes that port on the mesh as HTTP on port 80.

On the phone or the laptop, install Tailscale and log in to the control URL with the one-time key. The Tailscale app asks for a custom coordination server and an auth key. On a machine with the Tailscale command line, the same login is:

```bash
tailscale up --login-server=http://192.168.1.20:8443 --auth-key=ONE_TIME_KEY
```

Use the control URL from the setup page, and the phone key or the laptop key. Then open the Board at:

```text
http://friday.friday.mesh/
```

That name is the mesh hostname `friday` under the DNS base `friday.mesh`. If the Tailscale client shows a different name for this computer, open that name on port 80. The mesh carries the HTTP. Postgres, Qdrant, the memory service, and the executor are not given a mesh address.

## A lost Board password

On the text console of the Friday computer, after setup is complete, type `recover`. Type a new password of at least 12 characters, then type it again. The console prints the new password once. The same action from the Board, from another machine, or before setup is complete, is refused.

## The text console

The text console on the installed system accepts these commands while setup is open:

```text
status
link
wifi
server
name <display name>
timezone <Zone/Name>
model <base-url> <fast-model> [think-model]
key
password
finish
```

`model` then asks for the API key. `password` asks for the Board password twice. `wifi` asks for the network name and then the password.

The mesh buttons are on the setup page. The text console has no mesh command. Use the full-screen page for that choice.
