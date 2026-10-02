"""First-boot setup state. The page cannot install, grant, or read memory.

Secrets are written once, mode 0600, under the data directory. A second
call keeps the same values. Chat stays off until a model reply is
non-empty and the local embed reply is nomic-embed-text at 768 numbers.
A core start that returns that reply records it. A check that returns
nothing leaves the screen on not checked. Notes: empty is recorded
only when the smoke point was deleted and every collection count was
zero. A kept count is not called empty. A missed smoke point records
neither.
A credential-shaped fast or think name is refused and is not stored.
Another model id is refused, including when that vector is also 768 long.
A missing model id is refused. confirmed=true is not a field this module
stores. The pin is not a caller argument. Changing it is a new image.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from image import VERSION
from image.disks import BUNDLED
from image.mesh import choose_create, choose_join, choose_local
from image.starter import CODES
from memoryd.store import credential_shape

ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
SECRET_FILES = (
    "board_password",
    "notify_token",
    "memory_token",
    "qdrant_key",
    "postgres_password",
    "approval_token",
    "webhook_jellyfin",
    "webhook_radarr",
    "webhook_sonarr",
    "soul_apply_token",
)
MAX_KEY = 4096
MODEL_NAME_LIMIT = 128
PINNED_EMBED = "nomic-embed-text"
_EMBED_TAG = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


def accept_model_name(name: object) -> tuple[str, str]:
    """Return the stripped name and a reason. An empty reason means it can be posted.

    A blank name, a newline, or a name longer than 128 characters is
    model_missing. A credential-shaped name is credential, and the value
    is not returned.
    """
    if not isinstance(name, str):
        return "", "model_missing"
    cleaned = name.strip()
    if cleaned == "" or "\n" in cleaned or "\r" in cleaned or len(cleaned) > MODEL_NAME_LIMIT:
        return "", "model_missing"
    if credential_shape(cleaned):
        return "", "credential"
    return cleaned, ""


@dataclass(frozen=True)
class Outcome:
    outcome: str
    reason: str


@dataclass(frozen=True)
class Iface:
    name: str
    carrier: bool
    kind: str


class SystemRng:
    def token_hex(self, nbytes: int) -> str:
        import secrets

        return secrets.token_hex(nbytes)

    def password(self) -> str:
        import secrets

        raw = "".join(ALPHABET[secrets.randbelow(len(ALPHABET))] for _ in range(20))
        return "-".join(raw[i : i + 4] for i in range(0, 20, 4))


class FakeRng:
    def __init__(self, seed: int) -> None:
        import random

        self._random = random.Random(seed)

    def token_hex(self, nbytes: int) -> str:
        return "".join(f"{self._random.randrange(256):02x}" for _ in range(nbytes))

    def password(self) -> str:
        raw = "".join(ALPHABET[self._random.randrange(len(ALPHABET))] for _ in range(20))
        return "-".join(raw[i : i + 4] for i in range(0, 20, 4))


def same(left: str, right: str) -> bool:
    a = left.encode()
    b = right.encode()
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def observe(ifaces: list[Iface]) -> str:
    if any(iface.carrier and iface.kind == "wired" for iface in ifaces):
        return "wired"
    if any(iface.carrier and iface.kind == "wireless" for iface in ifaces):
        return "wireless"
    return "no_route"


def read_ifaces(net: Path) -> list[Iface]:
    found = []
    if not net.is_dir():
        return found
    for entry in sorted(net.iterdir()):
        if entry.name == "lo":
            continue
        try:
            carrier = (entry / "carrier").read_text().strip() == "1"
        except OSError:
            carrier = False
        wireless = (entry / "wireless").exists() or (entry / "phy80211").exists()
        found.append(Iface(entry.name, carrier, "wireless" if wireless else "wired"))
    return found


def reconcile_machine_id(etc: str, data: str, generated: str) -> tuple[str, str]:
    """Prefer the id already stored on the data partition, then the one systemd wrote."""
    etc = etc.strip()
    data = data.strip()
    if data:
        return data, data
    if etc:
        return etc, etc
    return generated, generated


def valid_name(name: str) -> bool:
    return bool(name) and name.strip() == name and "\n" not in name and len(name) <= 80


def valid_zone(name: str) -> bool:
    return bool(name) and len(name) <= 64 and re.fullmatch(r"[A-Za-z0-9_+/-]+", name) is not None


def address_forbidden(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_link_local or addr.is_multicast or addr.is_unspecified or addr.is_reserved


def vet_base(url: str, resolve) -> str | None:
    if not url or len(url) > 300 or any(ch.isspace() for ch in url):
        return "model_url"
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return "model_url"
    if parts.username or parts.password or parts.query or parts.fragment:
        return "model_url"
    host = parts.hostname.rstrip(".").lower()
    if host == "metadata.google.internal":
        return "model_address"
    literal = None
    try:
        literal = str(ipaddress.ip_address(host))
    except ValueError:
        literal = None
    addresses = [literal] if literal else list(resolve(host))
    if not addresses or any(address_forbidden(item) for item in addresses):
        return "model_address"
    return None


def chat_url(base: str) -> str:
    trimmed = base.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    if trimmed.endswith("/v1"):
        return trimmed + "/chat/completions"
    return trimmed + "/v1/chat/completions"


def reply_text(body: bytes) -> str:
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return ""
    if not isinstance(content, str):
        return ""
    return content.strip()


def embed_length(body: bytes) -> int:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    vector = _embed_vector(data)
    if vector is None:
        return 0
    return len(vector)


def pinned_model(model: object) -> bool:
    """True only for nomic-embed-text, or that name plus one tag."""
    if not isinstance(model, str):
        return False
    if model == PINNED_EMBED:
        return True
    prefix = PINNED_EMBED + ":"
    if not model.startswith(prefix):
        return False
    return _EMBED_TAG.fullmatch(model[len(prefix) :]) is not None


def pinned_embed(body: bytes) -> str:
    """ok, or why this reply is not the pinned 768-number embed.

    The model id has to be in the body. A 768-long vector from any other
    id, and a vector with no id, are both refused. This does not call
    Ollama.
    """
    if not isinstance(body, (bytes, bytearray)):
        return "embed_not_ready"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "embed_not_ready"
    if not isinstance(data, dict):
        return "embed_not_ready"
    if not pinned_model(data.get("model")):
        return "embed_model"
    vector = _embed_vector(data)
    if vector is None or len(vector) != 768 or not _embed_numbers(vector):
        return "embed_dimensions"
    return "ok"


def _embed_vector(data: dict) -> list | None:
    if "embeddings" in data:
        embeddings = data.get("embeddings")
        if isinstance(embeddings, list) and len(embeddings) == 1 and isinstance(embeddings[0], list):
            return embeddings[0]
        return None
    embedding = data.get("embedding")
    if isinstance(embedding, list):
        return embedding
    return None


def _embed_numbers(vector: list) -> bool:
    return all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in vector)


def ram_warning(mem_total_kib: int) -> str:
    if mem_total_kib < 6 * 1024 * 1024:
        return "This machine reports under 8 GB of RAM. The tested target is 8 GB or more."
    return ""


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.board_password = ""
        self.notify_token = ""
        self.memory_token = ""
        self.qdrant_key = ""
        self.postgres_password = ""
        self.approval_token = ""
        self.provision_token = ""
        self.machine_id = ""
        self.provision_state = "open"
        self.owner_name = ""
        self.timezone = ""
        self.link_saved = ""
        self.server_confirmed = False
        self.server_note = ""
        self.model_base = ""
        self.model_fast = ""
        self.model_think = ""
        self.model_key = ""
        self.model_ok = False
        self.embed_ok = False
        self.notes_state = ""
        self.password_confirmed = False
        self.webhook_jellyfin = ""
        self.webhook_radarr = ""
        self.webhook_sonarr = ""
        self.soul_apply_token = ""
        self.wifi_ssid = ""
        self.wifi_password = ""
        self.wifi_joined = False
        self.mesh_mode = ""
        self.mesh_url = ""
        self.mesh_port = "8443"
        self.mesh_auth_key = ""
        self.mesh_phone_key = ""
        self.mesh_laptop_key = ""
        self.joiner = None
        self.omitted: list[str] = []
        self.ifaces: list[Iface] = []
        self.transport = None
        self.embed_transport = None
        self.resolve = None
        self.zone_exists = lambda _name: True
        self.starter = None
        self.handoff = None
        self.started = False
        self.downloaded = False

    def load_or_mint(self, rng, etc_machine_id: str = "") -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        (self.root / "notes").mkdir(exist_ok=True)
        secret_dir = self.root / "secrets"
        secret_dir.mkdir(exist_ok=True)
        os.chmod(secret_dir, 0o700)
        existed = (secret_dir / "board_password").is_file()
        for name in SECRET_FILES:
            current = self._read_secret(name)
            if current:
                setattr(self, name, current)
            else:
                value = rng.password() if name == "board_password" else rng.token_hex(32)
                setattr(self, name, value)
                self._secret(name, value)
        token_path = self.root / "provision.token"
        state = self._read("provision_state") or "open"
        self.provision_state = state
        if state == "complete":
            self.provision_token = ""
            if token_path.exists():
                token_path.unlink()
        elif token_path.is_file() and token_path.read_text().strip():
            self.provision_token = token_path.read_text().strip()
        else:
            self.provision_token = rng.token_hex(32)
            self._write(token_path, self.provision_token, 0o600)
        self.owner_name = self._read("owner_name")
        self.timezone = self._read("timezone")
        self.link_saved = self._read("link")
        self.server_confirmed = self._read("server_confirmed") == "yes"
        self.server_note = self._read("server_note")
        self.model_base = self._read("model_base_url")
        self.model_fast = self._read("model_fast")
        self.model_think = self._read("model_think")
        self.model_key = self._read_secret("model_api_key")
        self.model_ok = self._read("model_ok") == "yes"
        self.embed_ok = self._read("embed_ok") == "yes"
        notes = self._read("notes_state")
        self.notes_state = notes if notes in {"empty", "kept"} else ""
        self.password_confirmed = self._read("password_confirmed") == "yes"
        self.wifi_ssid = self._read("wifi_ssid")
        self.wifi_password = self._read_secret("wifi_psk")
        self.wifi_joined = self._read("wifi_joined") == "yes"
        mode = self._read("mesh_mode")
        self.mesh_mode = mode if mode in {"local", "join", "create"} else ""
        self.mesh_url = self._read("mesh_url")
        self.mesh_port = self._read("mesh_port") or "8443"
        self.mesh_auth_key = self._read_secret("mesh_auth_key")
        self.mesh_phone_key = self._read_key("phone.key")
        self.mesh_laptop_key = self._read_key("laptop.key")
        data = self._read("machine-id")
        chosen, stored = reconcile_machine_id(etc_machine_id, data, rng.token_hex(16))
        self.machine_id = chosen
        if stored != data:
            self._text("machine-id", stored)
        (secret_dir / "minted").write_text("yes\n")
        os.chmod(secret_dir / "minted", 0o600)
        return "reused" if existed else "minted"

    def save_link(self) -> str:
        self.link_saved = observe(self.ifaces)
        self._text("link", self.link_saved)
        return self.link_saved

    def save_wifi(self, ssid: str, password: str) -> Outcome:
        if not ssid or not password or "\n" in ssid or "\n" in password:
            return Outcome("refused", "wifi_missing")
        self.wifi_ssid = ssid
        self.wifi_password = password
        self.wifi_joined = False
        self._text("wifi_ssid", ssid)
        self._text("wifi_joined", "no")
        self._secret("wifi_psk", password)
        if self.joiner is None:
            return Outcome("ok", "wifi_stored")
        try:
            self.joiner(ssid, password)
        except OSError as exc:
            reason = str(exc) if str(exc) in {"wifi_no_device", "wifi_join_failed", "wifi_missing"} else "wifi_join_failed"
            return Outcome("refused", reason)
        self.wifi_joined = True
        self._text("wifi_joined", "yes")
        return Outcome("ok", "wifi_joined")

    def set_mesh(self, mode: str, url: str = "", key: str = "") -> Outcome:
        """Record this computer, an existing mesh, or a mesh created here.

        A finished setup does not take a new choice. A caller-supplied key
        is stored only for join, and only after the charset check. Create
        does not keep a key the caller typed.
        """
        if self.provision_state == "complete":
            return Outcome("refused", "still_provisioning")
        if mode == "local":
            choice = choose_local()
        elif mode == "join":
            choice = choose_join(url, key)
        elif mode == "create":
            choice = choose_create(url)
        else:
            return Outcome("refused", "mesh_url")
        if choice.reason:
            return Outcome("refused", choice.reason)
        self._apply_mesh(choice)
        return Outcome("ok", "mesh_set")

    def save_mesh_keys(self, box: str, phone: str, laptop: str) -> None:
        """Store keys Headscale minted. The box key is not a status line."""
        if self.mesh_mode != "create":
            return
        if not box or not phone or not laptop:
            return
        if "\n" in box or "\n" in phone or "\n" in laptop:
            return
        self.mesh_auth_key = box
        self.mesh_phone_key = phone
        self.mesh_laptop_key = laptop
        self._secret("mesh_auth_key", box)
        self._write(self.root / "headscale" / "phone.key", phone, 0o600)
        self._write(self.root / "headscale" / "laptop.key", laptop, 0o600)

    def confirm_server(self) -> Outcome:
        missing = [name for name in BUNDLED if name in self.omitted]
        self.server_confirmed = True
        self.started = False
        self.downloaded = False
        self._text("server_confirmed", "yes")
        if missing:
            self.server_note = "core_not_in_image"
            self._text("server_note", self.server_note)
            return Outcome("recorded", "core_not_in_image")
        if self.starter is None:
            self.server_note = "start_not_wired"
            self._text("server_note", self.server_note)
            return Outcome("recorded", "start_not_wired")
        try:
            self.starter(self)
        except OSError as exc:
            reason = str(exc) if str(exc) in CODES else "start_failed"
            self.server_note = reason
            self._text("server_note", self.server_note)
            return Outcome("refused", reason)
        self.started = True
        self.server_note = "started"
        self._text("server_note", self.server_note)
        return Outcome("ok", "started")

    def set_name(self, name: str) -> Outcome:
        if not valid_name(name):
            return Outcome("refused", "name_invalid")
        self.owner_name = name
        self._text("owner_name", name)
        return Outcome("ok", "name_set")

    def set_timezone(self, name: str) -> Outcome:
        if not valid_zone(name):
            return Outcome("refused", "timezone_invalid")
        if not self.zone_exists(name):
            return Outcome("refused", "timezone_unknown")
        self.timezone = name
        self._text("timezone", name)
        return Outcome("ok", "timezone_set")

    def set_model(self, base: str, fast: str, think: str, key: str) -> Outcome:
        if not isinstance(key, str) or len(key) == 0 or len(key) > MAX_KEY or "\n" in key:
            return Outcome("refused", "model_missing")
        fast_name, reason = accept_model_name(fast)
        if reason:
            return Outcome("refused", reason)
        if not isinstance(think, str):
            return Outcome("refused", "model_missing")
        think_name = ""
        if think.strip() != "":
            think_name, reason = accept_model_name(think)
            if reason:
                return Outcome("refused", reason)
        self.model_base = base.strip()
        self.model_fast = fast_name
        self.model_think = think_name
        self.model_key = key
        self.model_ok = False
        self._text("model_base_url", self.model_base)
        self._text("model_fast", self.model_fast)
        self._text("model_think", self.model_think)
        self._text("model_ok", "no")
        self._secret("model_api_key", key)
        return self.check_model()

    def check_model(self) -> Outcome:
        if observe(self.ifaces) == "no_route":
            return Outcome("refused", "no_route")
        if not self.model_base or not self.model_fast or not self.model_key:
            return Outcome("refused", "model_missing")
        resolve = self.resolve or (lambda _host: [])
        reason = vet_base(self.model_base, resolve)
        if reason:
            return Outcome("refused", reason)
        if self.transport is None:
            return Outcome("refused", "model_unreachable")
        try:
            status, body = self.transport(chat_url(self.model_base), self.model_key, self.model_fast)
        except OSError:
            return Outcome("refused", "model_unreachable")
        if status != 200:
            return Outcome("refused", "model_rejected")
        if not reply_text(body):
            self.model_ok = False
            self._text("model_ok", "no")
            return Outcome("refused", "empty_reply")
        self.model_ok = True
        self._text("model_ok", "yes")
        return Outcome("ok", "model_ok")

    def check_embed(self) -> Outcome:
        if self.embed_transport is None:
            self._mark_embed(False)
            return Outcome("refused", "embed_not_in_image")
        try:
            status, body = self.embed_transport()
        except OSError:
            self._mark_embed(False)
            return Outcome("refused", "embed_not_in_image")
        if status != 200:
            self._mark_embed(False)
            return Outcome("refused", "embed_not_ready")
        reason = pinned_embed(body)
        if reason != "ok":
            self._mark_embed(False)
            return Outcome("refused", reason)
        self._mark_embed(True)
        return Outcome("ok", "embed_ok")

    def _mark_embed(self, ok: bool) -> None:
        self.embed_ok = ok
        self._text("embed_ok", "yes" if ok else "no")

    def mark_notes(self, state: str) -> None:
        if state not in {"empty", "kept"}:
            return
        self.notes_state = state
        self._text("notes_state", state)

    def confirm_password(self, typed: str, again: str) -> Outcome:
        if not typed or not same(typed, again) or not same(typed, self.board_password):
            return Outcome("refused", "password_mismatch")
        self.password_confirmed = True
        self._text("password_confirmed", "yes")
        return Outcome("ok", "password_confirmed")

    def finish(self) -> Outcome:
        if observe(self.ifaces) == "no_route":
            return Outcome("refused", "no_route")
        if not self.server_confirmed:
            return Outcome("refused", "server_not_confirmed")
        if not self.owner_name:
            return Outcome("refused", "name_missing")
        if not self.timezone:
            return Outcome("refused", "timezone_missing")
        if not self.model_ok:
            return Outcome("refused", "model_not_ready")
        if not self.password_confirmed:
            return Outcome("refused", "password_not_confirmed")
        embed = self.check_embed()
        if embed.outcome != "ok":
            return embed
        self.provision_state = "complete"
        self.provision_token = ""
        self._text("provision_state", "complete")
        token = self.root / "provision.token"
        if token.exists():
            token.unlink()
        if self.handoff is not None:
            self.handoff()
        return Outcome("complete", "ok")

    def recover(self, new_password: str, *, local_console: bool) -> Outcome:
        if not local_console:
            return Outcome("refused", "console_only")
        if self.provision_state != "complete":
            return Outcome("refused", "still_provisioning")
        if len(new_password) < 12 or "\n" in new_password:
            return Outcome("refused", "password_weak")
        self.board_password = new_password
        self._secret("board_password", new_password)
        return Outcome("ok", "password_replaced")

    def status_text(self) -> str:
        route = observe(self.ifaces)
        if self.link_saved and self.link_saved != route:
            link = f"{self.link_saved} saved, {route.replace('_', ' ')} now"
        elif route == "no_route":
            link = "no route"
        else:
            link = route
        lines = [f"Friday {VERSION}", ""]
        if self.provision_state != "complete":
            lines.append(f"Board password: {self.board_password}")
            lines.append(f"Character apply token: {self.soul_apply_token}")
            lines.append("")
        lines.append(f"Link: {link}")
        lines.extend(self._mesh_lines())
        if self.wifi_ssid:
            lines.append(f"Wi-Fi: password stored for {self.wifi_ssid}")
            if self.wifi_joined:
                lines.append(f"Wi-Fi: joined {self.wifi_ssid}")
            elif self.joiner is None:
                lines.append("This test image does not join Wi-Fi. A wired link is the one it can use.")
            else:
                lines.append("Wi-Fi was not joined. A wired link is the one it can use.")
        lines.append("Server: confirmed" if self.server_confirmed else "Server: not confirmed")
        if self.server_confirmed:
            if self.started or self.server_note == "started":
                lines.append("The core on this computer was started. Nothing was downloaded.")
            elif self.server_note in CODES:
                lines.append("The core did not start. Nothing was downloaded.")
            else:
                lines.append(
                    "Creating the server was recorded. Nothing was started and nothing was downloaded."
                )
            if self.server_note and not self.started:
                lines.append(f"Detail: {self.server_note}")
        lines.append(f"Name: {self.owner_name or 'not set'}")
        lines.append(f"Timezone: {self.timezone or 'not set'}")
        lines.append("Model: reply received" if self.model_ok else "Model: not checked")
        if self.embed_ok:
            lines.append("Embed: nomic-embed-text, 768")
        elif "nomic-embed-text" in self.omitted or "ollama" in self.omitted:
            lines.append("Embed: not in this image")
        else:
            lines.append("Embed: not checked")
        if self.notes_state == "empty":
            lines.append("Notes: empty")
        elif self.notes_state == "kept":
            lines.append("Notes: kept")
        lines.append("Password: confirmed" if self.password_confirmed else "Password: not confirmed")
        lines.append(f"Provision: {self.provision_state}")
        lines.append("")
        if self.omitted:
            lines.append("This image does not contain: " + ", ".join(self.omitted))
        lines.append("Catalog install is refused.")
        if "friday" in self.omitted or "nomic-embed-text" in self.omitted:
            lines.append("Friday does not speak in this image.")
        return "\n".join(lines) + "\n"

    def _mesh_lines(self) -> list[str]:
        if self.mesh_mode == "join" and self.mesh_url:
            return [f"Mesh: joining {self.mesh_url}"]
        if self.mesh_mode == "create" and self.mesh_url:
            lines = [f"Mesh: this computer. Other devices use {self.mesh_url}"]
            if self.provision_state != "complete":
                if self.mesh_phone_key and self.mesh_laptop_key:
                    lines.append(f"Phone key: {self.mesh_phone_key}")
                    lines.append(f"Laptop key: {self.mesh_laptop_key}")
                else:
                    lines.append("Phone and laptop keys appear after the server starts.")
            return lines
        return ["Mesh: this computer only"]

    def _apply_mesh(self, choice) -> None:
        if choice.mode in {"local", "create"}:
            self._drop_secret("mesh_auth_key")
            self.mesh_auth_key = ""
        if choice.mode != "create":
            self._drop_key("phone.key")
            self._drop_key("laptop.key")
            self.mesh_phone_key = ""
            self.mesh_laptop_key = ""
        if choice.mode == "join":
            self.mesh_auth_key = choice.key
            self._secret("mesh_auth_key", choice.key)
        self.mesh_mode = choice.mode
        self.mesh_url = choice.url
        self.mesh_port = choice.port
        self._text("mesh_mode", choice.mode)
        self._text("mesh_url", choice.url)
        self._text("mesh_port", choice.port)

    def _drop_secret(self, name: str) -> None:
        path = self.root / "secrets" / name
        if path.exists():
            path.unlink()

    def _read_key(self, name: str) -> str:
        path = self.root / "headscale" / name
        if not path.is_file():
            return ""
        return path.read_text().strip()

    def _drop_key(self, name: str) -> None:
        path = self.root / "headscale" / name
        if path.exists():
            path.unlink()

    def _secret(self, name: str, value: str) -> None:
        path = self.root / "secrets" / name
        self._write(path, value, 0o600)

    def _text(self, name: str, value: str) -> None:
        self._write(self.root / name, value, 0o644)

    def _write(self, path: Path, value: str, mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
        try:
            os.write(fd, (value + "\n").encode())
        finally:
            os.close(fd)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        os.chmod(path, mode)

    def _read(self, name: str) -> str:
        path = self.root / name
        if not path.is_file():
            return ""
        return path.read_text().strip()

    def _read_secret(self, name: str) -> str:
        path = self.root / "secrets" / name
        if not path.is_file():
            return ""
        return path.read_text().strip()


