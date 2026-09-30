"""Text console for the installer and the setup screen."""

from __future__ import annotations

from image import VERSION
from image.disks import REASONS, Disk, choose, format_size
from image.setup import Store, ram_warning


class InstallerConsole:
    def __init__(self, disks: list[Disk], *, installer_known: bool, mem_total_kib: int = 0) -> None:
        self.disks = disks
        self.installer_known = installer_known
        self.mem_total_kib = mem_total_kib
        self.phase = "ask"
        self.chosen = ""
        self.ready = False
        self.reboot = False

    def banner(self) -> str:
        rows = []
        for disk in self.disks:
            mark = "  installer" if disk.installer else ""
            rows.append(f"  {disk.name}  {format_size(disk.size_bytes)}{mark}")
        listing = "\n".join(rows) if rows else "  (no disks)"
        warning = ram_warning(self.mem_total_kib)
        extra = f"\n{warning}\n" if warning else "\n"
        return (
            f"Friday {VERSION} test installer\n\n"
            "This stick is only the installer. It does not become the system disk.\n"
            "The tested machine is x86_64, UEFI, with at least 8 GB of RAM "
            "and an internal disk of at least 64 GB. Secure Boot has to be off.\n\n"
            "This image contains Debian and the installer. It does not contain Friday, "
            "the Board, the memory service, Qdrant, Postgres, Ollama, or the embed model. "
            "Docker Engine is not in this test image. Catalog install is refused. There is no SSH.\n"
            f"{extra}"
            f"Disks:\n{listing}\n\n"
            "Type the kernel name of the internal disk, as listed above.\n"
        )

    def line(self, text: str) -> str:
        if self.phase == "reboot":
            if text.strip() == "reboot":
                self.reboot = True
                return "Rebooting.\n"
            return "Remove this stick, then type reboot.\n"
        if self.phase == "failed":
            return "The copy did not finish. The named disk may already be erased.\n"
        typed = text.strip()
        if self.phase == "ask":
            if not typed:
                return self.banner()
            decision = choose(self.disks, typed, installer_known=self.installer_known)
            if not decision.ok:
                return REASONS[decision.reason] + "\n"
            self.chosen = decision.name
            self.phase = "confirm"
            return (
                f"{decision.name} is {format_size(decision.size_bytes)}. "
                "Type the same name again to erase it and install Friday.\n"
            )
        if typed != self.chosen:
            self.phase = "ask"
            self.chosen = ""
            self.ready = False
            return "The second name did not match. Nothing was erased.\n"
        self.phase = "copying"
        self.ready = True
        return f"Erasing {self.chosen} and copying the installer onto slot A.\n"


class SetupConsole:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.phase = "ask"
        self.buf: dict[str, str] = {}

    def banner(self) -> str:
        return (
            self.store.status_text()
            + "\nCommands: status, link, wifi, server, name, timezone, model, key, password, finish\n"
            "Recovery, after setup is complete: recover\n"
        )

    def line(self, text: str) -> str:
        if self.phase == "wifi_ssid":
            self.buf["ssid"] = text.strip()
            self.phase = "wifi_psk"
            return "Wi-Fi password. It will be stored and not shown again.\n"
        if self.phase == "wifi_psk":
            outcome = self.store.save_wifi(self.buf.get("ssid", ""), text)
            self.phase = "ask"
            self.buf = {}
            if outcome.outcome != "ok":
                return outcome.reason + "\n"
            return self.store.status_text()
        if self.phase == "key":
            base = self.buf.get("base", "")
            fast = self.buf.get("fast", "")
            think = self.buf.get("think", "")
            self.phase = "ask"
            self.buf = {}
            outcome = self.store.set_model(base, fast, think, text.strip())
            return outcome.reason + "\n" + self.store.status_text()
        if self.phase == "password":
            self.buf["typed"] = text
            self.phase = "password_again"
            return "Type the Board password again.\n"
        if self.phase == "password_again":
            typed = self.buf.get("typed", "")
            self.phase = "ask"
            self.buf = {}
            outcome = self.store.confirm_password(typed, text)
            return outcome.reason + "\n" + self.store.status_text()
        if self.phase == "recover":
            self.buf["new"] = text
            self.phase = "recover_again"
            return "Type the new Board password again.\n"
        if self.phase == "recover_again":
            new = self.buf.get("new", "")
            self.phase = "ask"
            self.buf = {}
            if new != text:
                return "password_mismatch\n"
            outcome = self.store.recover(new, local_console=True)
            if outcome.outcome != "ok":
                return outcome.reason + "\n"
            return f"New Board password: {new}\n"

        parts = text.strip().split()
        if not parts:
            return self.banner()
        cmd, rest = parts[0], parts[1:]
        if cmd == "status":
            return self.store.status_text()
        if cmd == "link":
            self.store.save_link()
            return self.store.status_text()
        if cmd == "wifi":
            self.phase = "wifi_ssid"
            return "Wi-Fi name.\n"
        if cmd == "server":
            outcome = self.store.confirm_server()
            return outcome.reason + "\n" + self.store.status_text()
        if cmd == "name":
            outcome = self.store.set_name(" ".join(rest))
            return outcome.reason + "\n" + self.store.status_text()
        if cmd == "timezone":
            outcome = self.store.set_timezone(rest[0] if rest else "")
            return outcome.reason + "\n" + self.store.status_text()
        if cmd == "model":
            if len(rest) < 2:
                return "model <base-url> <fast-model> [think-model]\n"
            self.buf = {"base": rest[0], "fast": rest[1], "think": rest[2] if len(rest) > 2 else ""}
            self.phase = "key"
            return "Model API key. It will be stored and not shown again.\n"
        if cmd == "key":
            return "Use model first, then the key prompt.\n"
        if cmd == "password":
            self.phase = "password"
            return "Type the Board password.\n"
        if cmd == "finish":
            outcome = self.store.finish()
            return outcome.reason + "\n" + self.store.status_text()
        if cmd == "recover":
            self.phase = "recover"
            return "New Board password. This console is the only place it can be replaced.\n"
        if cmd in {"install", "uninstall"}:
            return "refused\ncatalog_install_closed\n"
        if cmd == "grant":
            return "refused\ngrant_closed\n"
        if cmd in {"memory", "recall"}:
            return "refused\nmemory_unreadable\n"
        if cmd == "confirmed":
            return "ignored\n" + self.store.status_text()
        return "unknown\n" + self.banner()
