"""One fire writes the core Helm chart. Two pods do not share Friday."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from deploy.helm.chart import (
    CHART_FILES,
    CORE,
    EXCLUDED,
    Decision,
    access_mode,
    fire,
    rollout,
)
from image import VERSION

ROOT = Path(__file__).resolve().parents[1]
KEPT = "The password is kept outside the machine"
TOKEN = "token=abcd"


def _fire(dest: Path, **extra: object):
    fields = {"actor": "board", "confirmed": False, "cluster_supports_rwop": True}
    fields.update(extra)
    return fire(dest, **fields)


def _text(dest: Path) -> str:
    parts = []
    for relative in CHART_FILES:
        parts.append((dest / relative).read_text(encoding="utf-8"))
    return "\n".join(parts)


def _docs(text: str) -> list[str]:
    return [chunk.strip() for chunk in text.split("---") if chunk.strip()]


def _kind(doc: str) -> str:
    for line in doc.splitlines():
        if line.startswith("kind:"):
            return line.split(":", 1)[1].strip()
    return ""


def _meta_name(doc: str) -> str:
    in_meta = False
    for line in doc.splitlines():
        if line.startswith("metadata:"):
            in_meta = True
            continue
        if in_meta and line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
        if in_meta and line and not line.startswith(" "):
            break
    return ""


class HelmChartTests(unittest.TestCase):
    def test_one_fire_writes_the_core_chart(self) -> None:
        with TemporaryDirectory() as raw:
            dest = Path(raw) / "helm"
            decision = _fire(dest, confirmed=True, note=KEPT)
            self.assertEqual(decision.outcome, "written")
            self.assertEqual(decision.reason, "core")
            self.assertEqual(decision.services, CORE)
            self.assertEqual(decision.strategy, "Recreate")
            self.assertEqual(decision.access_mode, "ReadWriteOncePod")
            self.assertIs(decision.applied, False)
            self.assertIs(decision.started, False)
            self.assertIs(decision.written, True)
            self.assertNotIn("confirmed", decision.__dict__)
            self.assertNotIn("note", decision.__dict__)
            self.assertNotIn("said", decision.__dict__)
            self.assertNotIn(KEPT, repr(decision))
            blob = _text(dest)
            self.assertNotIn(KEPT, blob)
            workloads = (dest / "templates" / "workloads.yaml").read_text(encoding="utf-8")
            names = [_meta_name(doc) for doc in _docs(workloads) if _kind(doc) == "Deployment"]
            services = [_meta_name(doc) for doc in _docs(workloads) if _kind(doc) == "Service"]
            self.assertEqual(tuple(names), CORE)
            self.assertEqual(tuple(services), CORE)
            roles = {}
            for doc in _docs(workloads):
                if _kind(doc) != "Deployment":
                    continue
                self.assertIn("replicas: 1\n", doc)
                self.assertIn("type: Recreate\n", doc)
                self.assertNotIn("RollingUpdate", doc)
                self.assertNotIn("hostNetwork", doc)
                self.assertNotIn("hostPort", doc)
                self.assertNotIn("privileged", doc)
                self.assertNotIn("docker.sock", doc)
                self.assertNotIn("NodePort", doc)
                for line in doc.splitlines():
                    if "friday.os/role:" in line:
                        roles[_meta_name(doc)] = line.split(":", 1)[1].strip()
            self.assertEqual(roles["ollama"], "embed-worker")
            self.assertEqual(roles["memory-mcp"], "index-reconciler")
            self.assertEqual(roles["friday"], "friday")
            self.assertEqual(workloads.count("claimName: friday"), 1)
            friday = next(doc for doc in _docs(workloads) if _kind(doc) == "Deployment" and _meta_name(doc) == "friday")
            self.assertIn("claimName: friday", friday)
            self.assertIn("FRIDAY_STATE", friday)
            self.assertIn("/data/friday.sqlite", friday)
            for doc in _docs(workloads):
                if _kind(doc) == "Deployment" and _meta_name(doc) != "friday":
                    self.assertNotIn("claimName: friday", doc)
            chart = (dest / "Chart.yaml").read_text(encoding="utf-8")
            self.assertIn("name: friday-core\n", chart)
            self.assertIn(f"version: {VERSION}\n", chart)
            pvc = (dest / "templates" / "pvc.yaml").read_text(encoding="utf-8")
            self.assertIn("ReadWriteOncePod", pvc)
            self.assertIn("ReadWriteOnce", pvc)
            self.assertIn("clusterSupportsReadWriteOncePod", pvc)
            self.assertNotIn("ReadWriteMany", pvc)
            values = (dest / "values.yaml").read_text(encoding="utf-8")
            self.assertIn("clusterSupportsReadWriteOncePod: true\n", values)
            self.assertIn("name: friday\n", values)
            body = "\n".join((workloads, pvc, chart, values))
            for name in EXCLUDED:
                self.assertNotIn(f"name: {name}\n", body)
                self.assertNotIn(f"/{name}:", body)
            self.assertNotIn("kind: Secret", blob)
            self.assertNotIn("POSTGRES_PASSWORD=", blob)
            self.assertNotIn("asikmydeen", blob)
            again = _fire(dest)
            self.assertEqual(again.reason, "core")
            self.assertEqual(_text(dest), blob)
            self.assertEqual(sorted(path.name for path in dest.rglob("*") if path.is_file()), sorted(
                Path(relative).name for relative in CHART_FILES
            ))

    def test_without_read_write_once_pod_recreate_stays(self) -> None:
        with TemporaryDirectory() as raw:
            dest = Path(raw) / "helm"
            decision = _fire(dest, cluster_supports_rwop="yes")
            self.assertEqual(decision.access_mode, "ReadWriteOnce")
            self.assertEqual(access_mode(False), "ReadWriteOnce")
            self.assertEqual(access_mode(True), "ReadWriteOncePod")
            values = (dest / "values.yaml").read_text(encoding="utf-8")
            self.assertIn("clusterSupportsReadWriteOncePod: false\n", values)
            workloads = (dest / "templates" / "workloads.yaml").read_text(encoding="utf-8")
            self.assertIn("type: Recreate", workloads)
            supported = Path(raw) / "supported"
            supported.mkdir()
            _fire(supported, cluster_supports_rwop=True)
            same = (dest / "templates" / "workloads.yaml").read_text(encoding="utf-8")
            self.assertEqual(same, (supported / "templates" / "workloads.yaml").read_text(encoding="utf-8"))

    def test_chat_cannot_fire_and_a_sentence_is_not_stored(self) -> None:
        with TemporaryDirectory() as raw:
            dest = Path(raw) / "helm"
            first = _fire(dest)
            before = _text(dest)
            for actor in ("chat", "Chat", " chat ", "friday", "executor", "board "):
                decision = _fire(dest, actor=actor, note=KEPT, confirmed=True)
                reason = "chat_cannot_write" if actor.strip().casefold() == "chat" else "actor_cannot_write"
                self.assertEqual(decision.reason, reason, actor)
                self.assertIs(decision.written, False)
                self.assertIs(decision.started, False)
                self.assertIs(decision.applied, False)
                self.assertNotIn(KEPT, repr(decision))
            self.assertEqual(_text(dest), before)
            self.assertEqual(first.services, CORE)
            empty = Path(raw) / "empty"
            empty.mkdir()
            said = _fire(empty, note="the helm chart is written")
            blob = _text(empty)
            self.assertNotIn("the helm chart is written", blob)
            self.assertNotIn("said", said.__dict__)

    def test_a_credential_shaped_note_is_not_stored(self) -> None:
        with TemporaryDirectory() as raw:
            dest = Path(raw) / "helm"
            dest.mkdir()
            for secret in (TOKEN, "token%3Dabcd", "password+is+hunter22", "token%253Dabcd"):
                decision = _fire(dest, note=secret, confirmed=True)
                self.assertEqual(decision.reason, "credential")
                self.assertEqual(decision.services, ())
                self.assertIs(decision.written, False)
                self.assertNotIn("abcd", repr(decision))
                self.assertNotIn("hunter22", repr(decision))
                self.assertNotIn(secret, repr(decision))
            self.assertEqual(list(dest.iterdir()), [])

    def test_a_relative_path_or_a_symlink_is_refused(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            link.symlink_to(real, target_is_directory=True)
            decision = _fire(link, confirmed=True)
            self.assertEqual(decision.reason, "path")
            self.assertIs(decision.written, False)
            self.assertEqual(list(real.iterdir()), [])
            relative = _fire(Path("deploy/helm"))
            self.assertEqual(relative.reason, "path")
            self.assertIs(relative.written, False)
            nested = root / "gone" / "helm"
            self.assertEqual(_fire(nested).reason, "path")
            file_dest = root / "file"
            file_dest.write_text("x", encoding="utf-8")
            self.assertEqual(_fire(file_dest).reason, "path")

    def test_upgrade_and_rollback_never_mount_the_volume_together(self) -> None:
        with TemporaryDirectory() as raw:
            dest = Path(raw) / "helm"
            _fire(dest, cluster_supports_rwop=False)
            workloads = (dest / "templates" / "workloads.yaml").read_text(encoding="utf-8")
        overlap = ("friday-old", "friday-new")
        self.assertEqual(len(overlap), 2)
        for direction in ("upgrade", "rollback"):
            samples = rollout(workloads, direction)
            self.assertEqual([sample.phase for sample in samples], ["running", "released", "started"])
            released = False
            first = None
            for sample in samples:
                self.assertLessEqual(len(sample.mounting), 1)
                self.assertNotEqual(sample.mounting, overlap)
                pods = dict(sample.pods)
                for name in ("friday", "ollama", "memory-mcp"):
                    self.assertLessEqual(len(pods[name]), 1, direction)
                if sample.phase == "running":
                    first = sample.mounting
                    self.assertEqual(len(sample.mounting), 1)
                if sample.phase == "released":
                    self.assertEqual(sample.mounting, ())
                    for name in pods:
                        self.assertEqual(pods[name], ())
                    released = True
                if sample.phase == "started":
                    self.assertTrue(released)
                    self.assertEqual(len(sample.mounting), 1)
                    self.assertNotEqual(sample.mounting, first)
                    self.assertEqual(sample.mounting, dict(sample.pods)["friday"])
        broken = workloads.replace("type: Recreate", "type: RollingUpdate", 1)
        self.assertEqual(rollout(broken, "upgrade")[0].phase, "overlap")
        self.assertEqual(len(rollout(broken, "upgrade")[0].mounting), 2)
        self.assertEqual(rollout(broken, "rollback")[0].phase, "overlap")

    def test_ask_does_not_call_it_and_the_image_copies_it(self) -> None:
        ask = (ROOT / "friday" / "ask.py").read_text(encoding="utf-8")
        self.assertNotIn("deploy.helm", ask)
        self.assertNotIn("deploy/helm", ask)
        script = (ROOT / "image" / "build-inside.sh").read_text(encoding="utf-8")
        self.assertIn("/src/deploy/helm/Chart.yaml", script)
        self.assertIn("/src/deploy/helm/templates/workloads.yaml", script)
        self.assertIn("/src/deploy/helm/templates/pvc.yaml", script)
        self.assertIn("usr/lib/friday/helm/Chart.yaml", script)
        self.assertIn("usr/lib/friday/helm/templates/workloads.yaml", script)
        stamp = (ROOT / "scripts" / "fetch-core.sh").read_text(encoding="utf-8")
        self.assertIn('"$ROOT/deploy/helm"', stamp)
        source = (ROOT / "deploy" / "helm" / "chart.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn("kubectl", source)
        self.assertNotIn("urllib.request", source)
        self.assertNotIn("import socket", source)
        tree = ROOT / "deploy" / "helm"
        with TemporaryDirectory() as raw:
            dest = Path(raw) / "helm"
            decision = _fire(dest)
            self.assertIsInstance(decision, Decision)
            for relative in CHART_FILES:
                self.assertEqual(
                    (dest / relative).read_text(encoding="utf-8"),
                    (tree / relative).read_text(encoding="utf-8"),
                    relative,
                )


if __name__ == "__main__":
    unittest.main()
