#!/usr/bin/env python3
"""Restore all in-scope apps from their latest backup, no arguments needed.

Discovers each app's newest backup object (SeaweedFS first, falling
back to that app's own cloud target(s) if SeaweedFS is unreachable),
downloads it, decrypts it with the controller's GPG key, prints one
batch confirmation summary, then runs the existing per-app
`playbooks/restore.yaml` for each app in order — step-ca first (see
docs/restore.md's batch-restore section for why), the rest after. A
step-ca failure — discovery or restore — aborts the whole batch; a
failure in any other app is independent and doesn't block the rest.

This never touches GPG/SeaweedFS/cloud credentials directly in Python —
it shells out to `rclone` (against a controller-local rclone.conf
rendered by the `restore_discovery` role) and to `gpg`, and delegates
the actual stop/extract/redeploy to the already-tested `restore` role
via `ansible-playbook`, the same as a manual per-app restore would. See
docs/restore.md's batch-restore section for the full design, and
docs/fire-drill.md for how to validate this against real infrastructure
(a real fire drill is a manual step, not run by CI or by this script
itself).

Requires, on the controller (see docs/disaster-recovery.md's Threat
model for why this only ever runs on a dedicated/hardened admin
machine):
  - `rclone` and `gpg` on PATH.
  - The backup GPG private key imported, with gpg-agent able to decrypt
    non-interactively (already unlocked, or a passphrase-less key) —
    this script never prompts for a GPG passphrase itself.
  - Every secret in secrets_registry.yaml already populated (see
    docs/cloud-credential-creation.md) — this script doesn't create or
    rotate any credential.

Usage:
    python3 ansible/restore_all.py            # interactive: prints a
                                                # summary, asks for a
                                                # single 'yes'
    python3 ansible/restore_all.py --yes       # unattended: skips the
                                                # confirmation prompt

Exit status: 0 if every in-scope app restored successfully, 1 otherwise
(including an aborted batch).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANSIBLE_DIR = PROJECT_ROOT / "ansible"
RESTORE_DIR = ANSIBLE_DIR / "files/restore"
MANIFEST_PATH = RESTORE_DIR / "manifest.json"
RCLONE_CONF_PATH = RESTORE_DIR / "rclone.conf"
SCRATCH_DIR = RESTORE_DIR / "scratch"
AUDIT_LOG_PATH = RESTORE_DIR / "audit-log.jsonl"

# BACKUP_FILENAME (backup_agent/templates/schedule.env.j2) is always
# "<host>-<app>-%Y-%m-%dT%H-%M-%S.<ext>", then docker-volume-backup
# appends ".gpg" on top when GPG_PUBLIC_KEY_RING_FILE is set (confirmed
# against offen/docker-volume-backup's own "Encrypting backups" docs —
# "the backup archive will be ... saved as a .gpg file instead"). <ext>
# varies by app (tar.gz/tar/tar.zst per BACKUP_COMPRESSION), so this
# only anchors on the timestamp, not the full filename.
_TIMESTAMP_RE = r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})"
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H-%M-%S"


class RestoreAllError(RuntimeError):
    """A per-app problem that should be reported and skipped, not raised past main()."""


@dataclass
class AppManifestEntry:
    app: str
    host: str
    seaweedfs_path: str
    volumes: list[str]
    cloud_targets: list[dict[str, str]]


@dataclass
class DiscoveryResult:
    entry: AppManifestEntry
    source: str
    object_name: str
    backup_timestamp: datetime
    decrypted_path: Path


def load_manifest() -> tuple[str, list[AppManifestEntry]]:
    if not MANIFEST_PATH.exists():
        raise SystemExit(
            f"{MANIFEST_PATH} not found — run this script again after "
            "playbooks/restore-discovery-setup.yaml has rendered it (this "
            "script normally runs that step itself; see docs/restore.md)."
        )
    data = json.loads(MANIFEST_PATH.read_text())
    entries = [AppManifestEntry(**app) for app in data["apps"]]
    return data["seaweedfs_bucket"], entries


def run_discovery_setup() -> None:
    print("Rendering the batch-restore manifest and rclone.conf...")
    result = subprocess.run(
        [
            "ansible-playbook",
            "playbooks/bootstrap-secrets.yaml",
            "playbooks/restore-discovery-setup.yaml",
            "-i",
            "inventory/inventory.yaml",
            "--limit",
            "localhost",
        ],
        cwd=ANSIBLE_DIR,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("restore-discovery-setup.yaml failed — see the output above.")


def _run_rclone(args: list[str], timeout: int) -> subprocess.CompletedProcess | None:
    """Run an rclone subcommand. None means it didn't complete cleanly (unreachable or hung).

    --contimeout/--timeout/--low-level-retries=1 make rclone fail fast on
    a genuinely dead endpoint — confirmed live that a closed port doesn't
    always refuse instantly (depends on the network path: a dropped SYN
    hangs until something's own connect timeout fires, rather than an
    immediate RST), so without these an unreachable SeaweedFS could stall
    the whole batch restore for rclone's own default retry/backoff
    duration before ever reaching the cloud fallback. `timeout=` below is
    a hard Python-level backstop on top of that, in case even those flags
    don't bound it — never raises past this function; a stall of any kind
    is folded into "treat this remote as unreachable," the same as a
    non-zero exit.
    """
    cmd = ["rclone", "--config", str(RCLONE_CONF_PATH), "--contimeout", "5s", "--timeout", "20s", "--low-level-retries", "1", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None


def rclone_lsjson(remote: str, bucket: str, prefix: str) -> list[dict] | None:
    """List objects under remote:bucket/prefix. None means unreachable (not: empty)."""
    result = _run_rclone(["lsjson", f"{remote}:{bucket}/{prefix}"], timeout=45)
    # NEEDS LIVE VERIFICATION — see docs/restore.md's batch-restore
    # section: an existing-but-empty prefix vs. a genuinely missing
    # bucket may not be distinguishable this way. The unreachable/hung
    # case is already handled and confirmed live — see _run_rclone.
    if result is None or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def pick_latest(objects: list[dict], host: str, app: str) -> tuple[str, datetime] | None:
    pattern = re.compile(r"^" + re.escape(f"{host}-{app}-") + _TIMESTAMP_RE + r"\.")
    best: tuple[str, datetime] | None = None
    for obj in objects:
        name = obj.get("Name", "")
        match = pattern.match(name)
        if not match:
            continue
        timestamp = datetime.strptime(match.group(1), _TIMESTAMP_FORMAT).replace(tzinfo=UTC)
        if best is None or timestamp > best[1]:
            best = (name, timestamp)
    return best


def discover_and_decrypt(entry: AppManifestEntry, seaweedfs_bucket: str) -> DiscoveryResult:
    source = bucket = prefix = None
    objects: list[dict] = []

    seaweedfs_objects = rclone_lsjson("seaweedfs", seaweedfs_bucket, entry.seaweedfs_path)
    if seaweedfs_objects is not None:
        source, bucket, prefix, objects = "seaweedfs", seaweedfs_bucket, entry.seaweedfs_path, seaweedfs_objects
    else:
        for target in entry.cloud_targets:
            candidate = rclone_lsjson(target["name"], target["bucket"], entry.seaweedfs_path)
            if candidate:
                source, bucket, prefix, objects = target["name"], target["bucket"], entry.seaweedfs_path, candidate
                break
        if source is None:
            tried = ", ".join(t["name"] for t in entry.cloud_targets)
            raise RestoreAllError(f"SeaweedFS unreachable and no cloud fallback ({tried}) had any objects either")

    if not objects:
        raise RestoreAllError(f"{source} reachable but no objects found under {prefix}/")

    latest = pick_latest(objects, entry.host, entry.app)
    if latest is None:
        raise RestoreAllError(
            f"none of the {len(objects)} object(s) under {prefix}/ on {source} match the expected '{entry.host}-{entry.app}-<timestamp>.*' filename pattern"
        )
    name, backup_timestamp = latest

    if not name.endswith(".gpg"):
        raise RestoreAllError(
            f"{name} has no .gpg suffix — every backup_agent archive is GPG-encrypted "
            "(GPG_PUBLIC_KEY_RING_FILE); refusing to hand an unexpected file to gpg --decrypt"
        )

    SCRATCH_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    encrypted_path = SCRATCH_DIR / name
    # A real download, not a listing — a generous overall backstop
    # since archives can be large (e.g. minecraft's); --contimeout/
    # --low-level-retries above (via _run_rclone) still fail fast if the
    # connection itself never comes up. NEEDS LIVE VERIFICATION for
    # slow/high-latency links — see docs/restore.md's batch-restore
    # section.
    copy_result = _run_rclone(["copyto", f"{source}:{bucket}/{prefix}/{name}", str(encrypted_path)], timeout=1800)
    if copy_result is None:
        raise RestoreAllError(f"rclone copyto from {source} timed out or was interrupted")
    if copy_result.returncode != 0:
        raise RestoreAllError(f"rclone copyto from {source} failed: {copy_result.stderr.strip()}")

    decrypted_path = SCRATCH_DIR / name[: -len(".gpg")]
    # --batch --yes, no --passphrase/--pinentry-mode: relies entirely on
    # gpg-agent already holding the unlocked private key (see this
    # script's module docstring) — never prompts. Generous timeout for
    # the same reason as the copy above (large archives); a hang here
    # would mean gpg-agent itself is stuck, not a network condition.
    try:
        gpg_result = subprocess.run(
            ["gpg", "--batch", "--yes", "-o", str(decrypted_path), "-d", str(encrypted_path)],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RestoreAllError(
            "gpg --decrypt hung for 10 minutes — is gpg-agent waiting on a passphrase prompt with no tty to answer it on? See this script's module docstring."
        ) from None
    encrypted_path.unlink(missing_ok=True)
    if gpg_result.returncode != 0:
        raise RestoreAllError(f"gpg --decrypt failed: {gpg_result.stderr.strip()} — is the private key loaded and gpg-agent unlocked non-interactively?")

    return DiscoveryResult(
        entry=entry,
        source=source,
        object_name=name,
        backup_timestamp=backup_timestamp,
        decrypted_path=decrypted_path,
    )


def print_summary(results: dict[str, DiscoveryResult], errors: dict[str, str]) -> None:
    print("\n--- Batch restore summary ---")
    rows = [("APP", "HOST", "SOURCE", "OBJECT", "TIMESTAMP")]
    for entry_app, result in results.items():
        rows.append(
            (
                entry_app,
                result.entry.host,
                result.source,
                result.object_name,
                result.backup_timestamp.isoformat(),
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    for row in rows:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)))
    if errors:
        print("\nFAILED DISCOVERY (will not be restored):")
        for app, message in errors.items():
            print(f"  {app}: {message}")


def append_audit_log(entries: list[dict]) -> None:
    RESTORE_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    with AUDIT_LOG_PATH.open("a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def run_app_restore(result: DiscoveryResult) -> bool:
    # A single JSON-object -e argument, not separate -e key=value pairs —
    # confirmed live: -e restore_volumes='["x"]' (key=value form) leaves
    # restore_volumes as the literal 17-character STRING '["x"]', not a
    # list — the restore role's own `| join(', ')` on it then iterates
    # per character (visible directly in the pause prompt: "[, ", x, ",
    # ]"), and its `loop: "{{ restore_volumes }}"` would do the same
    # against real volume names. `restore_confirm` happens to survive
    # the same string-typing because the role applies `| bool` to it;
    # `restore_volumes` has no such filter and needs to actually be a
    # list. A single JSON-object -e argument (confirmed live, see above)
    # gets every value's real type instead.
    extra_vars = {
        "restore_app": result.entry.app,
        "restore_archive_local_path": str(result.decrypted_path),
        "restore_volumes": result.entry.volumes,
        "restore_confirm": True,
    }
    cmd = [
        "ansible-playbook",
        "playbooks/bootstrap-secrets.yaml",
        "playbooks/restore.yaml",
        "-i",
        "inventory/inventory.yaml",
        "--limit",
        f"{result.entry.host},localhost",
        "-e",
        json.dumps(extra_vars),
    ]
    print(f"\n=== Restoring {result.entry.app} on {result.entry.host} ===")
    return subprocess.run(cmd, cwd=ANSIBLE_DIR, check=False).returncode == 0


def run_minecraft_world_restore() -> bool:
    cmd = [
        "ansible-playbook",
        "playbooks/bootstrap-secrets.yaml",
        "playbooks/restore-minecraft-world.yaml",
        "-i",
        "inventory/inventory.yaml",
        "--limit",
        "play,localhost",
    ]
    print("\n=== Unpacking the restored backup into minecraft's live world ===")
    return subprocess.run(cmd, cwd=ANSIBLE_DIR, check=False).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the confirmation prompt (for unattended/fire-drill automation)",
    )
    args = parser.parse_args()

    run_discovery_setup()
    seaweedfs_bucket, manifest_entries = load_manifest()

    results: dict[str, DiscoveryResult] = {}
    errors: dict[str, str] = {}
    for entry in manifest_entries:
        print(f"Discovering {entry.app} ({entry.host})...")
        try:
            results[entry.app] = discover_and_decrypt(entry, seaweedfs_bucket)
        except RestoreAllError as exc:
            errors[entry.app] = str(exc)

    print_summary(results, errors)

    if "step-ca" not in results:
        print(
            "\nstep-ca could not be discovered/decrypted — aborting the whole batch "
            "(lldap and tinyauth read its root cert on deploy, see deploy.yaml Play 6). "
            "Nothing has been restored."
        )
        return 1

    if not args.yes:
        answer = input("\nType 'yes' to STOP and overwrite all apps listed above: ")
        if answer != "yes":
            print("Aborted — confirmation not given. Nothing has been restored.")
            return 1

    audit_entries = []
    overall_ok = True

    # step-ca first, and its failure aborts everything else — see this
    # script's module docstring.
    step_ca_result = results["step-ca"]
    step_ca_ok = run_app_restore(step_ca_result)
    audit_entries.append(
        {
            "restored_at": datetime.now(UTC).isoformat(),
            "app": "step-ca",
            "host": step_ca_result.entry.host,
            "source": step_ca_result.source,
            "object": step_ca_result.object_name,
            "backup_timestamp": step_ca_result.backup_timestamp.isoformat(),
            "status": "success" if step_ca_ok else "failed",
        }
    )
    step_ca_result.decrypted_path.unlink(missing_ok=True)
    append_audit_log(audit_entries)

    if not step_ca_ok:
        print("\nstep-ca restore failed — aborting the rest of the batch.")
        return 1

    for app, result in results.items():
        if app == "step-ca":
            continue
        ok = run_app_restore(result)
        if ok and app == "minecraft":
            ok = run_minecraft_world_restore()
        overall_ok = overall_ok and ok
        append_audit_log(
            [
                {
                    "restored_at": datetime.now(UTC).isoformat(),
                    "app": app,
                    "host": result.entry.host,
                    "source": result.source,
                    "object": result.object_name,
                    "backup_timestamp": result.backup_timestamp.isoformat(),
                    "status": "success" if ok else "failed",
                }
            ]
        )
        result.decrypted_path.unlink(missing_ok=True)

    if errors:
        overall_ok = False
        print(f"\n{len(errors)} app(s) were never restored — see FAILED DISCOVERY above: {', '.join(errors)}")

    print(f"\nAudit log: {AUDIT_LOG_PATH}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
