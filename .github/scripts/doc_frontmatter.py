"""Shared YAML-frontmatter reading, validation, and decision-lineage
loading for generate-doc-indexes.py, check-doc-drift.py, and
doc_graph.py. Not a standalone script.

This module is the schema of record for every `type`, `status`,
`topic`, and relation field on docs/decisions/** and docs/projects/*.md.
Validation is by location: a doc's directory decides which `type` and
which `status` values it may carry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# `topic:` values, in the order the generated decisions index lists them.
TOPICS = {
    "deployment-platform": "Deployment & platform",
    "ingress-tls-pki": "Ingress, TLS & PKI",
    "secrets-store": "Secrets store",
    "cloud-credentials": "Cloud credentials",
    "backup-recovery": "Backup & recovery",
    "monitoring-alerting": "Monitoring & alerting",
    "repository-tooling": "Repository & tooling",
    "security-hardening": "Security & hardening",
    "documentation-process": "Documentation & process",
}

ADR_REVISION_STATUS = {"working", "approved", "accepted", "superseded", "abandoned", "retired"}
PROJECT_LIFECYCLE_STATUS = {"not-started", "de-risking", "building", "done"}
PROJECT_LEGACY_STATUS = {"in-progress", "blocked"}

# Kinds are decided by path: a lineage revision or a project.
# `in-progress`/`blocked` (project) are the pre-lifecycle vocabulary,
# valid until each project doc is migrated.
VALID_STATUS = {
    "adr-revision": ADR_REVISION_STATUS,
    "project": PROJECT_LIFECYCLE_STATUS | PROJECT_LEGACY_STATUS,
}
KIND_TYPE = {"adr-revision": "adr", "project": "project"}

REVISION_PATH_RE = re.compile(r"docs/decisions/(\d{4})-[a-z0-9-]+/revision-(\d{3})(?:-([a-z]))?\.md$")
LINEAGE_DIR_RE = re.compile(r"^\d{4}-[a-z0-9-]+$")
REVISION_FILE_RE = re.compile(r"^revision-(\d{3})(?:-([a-z]))?\.md$")
ADR_ID_RE = re.compile(r"^ADR-\d{4}$")
# A revision is named by its label: the generation number, plus a candidate
# letter when several competing solutions share that generation ("0", "1-b").
REVISION_LABEL = r"(?:0|[1-9]\d*)(?:-[a-z])?"
REVISION_REF_RE = re.compile(rf"^(ADR-\d{{4}})/({REVISION_LABEL})$")
PROJECT_ID_RE = re.compile(r"^PROJ-[a-z0-9-]+$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def doc_kind(path: Path) -> str:
    posix = path.as_posix()
    if REVISION_PATH_RE.search(posix):
        return "adr-revision"
    if "docs/decisions/" in posix:
        raise SystemExit(f"{path}: docs/decisions/ holds lineage directories (NNNN-slug/revision-NNN.md) only")
    if "docs/projects/" in posix:
        return "project"
    raise SystemExit(f"{path}: not under docs/decisions/ or docs/projects/")


def _fail(path: Path, msg: str) -> None:
    raise SystemExit(f"{path}: {msg}")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def ref_label(value: object) -> str | None:
    """Normalizes a revision reference from frontmatter — an integer generation
    (`0`) or a lettered candidate (`0-b`) — to its label, or None if malformed."""
    if _is_int(value) and value >= 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"(?:0|[1-9]\d*)-[a-z]", value):
        return value
    return None


def _require_text(path: Path, data: dict, field: str) -> None:
    if not isinstance(data.get(field), str) or not data[field].strip():
        _fail(path, f"frontmatter needs a non-empty '{field}' field")


def _id_list(path: Path, data: dict, field: str) -> None:
    value = data.get(field, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and ADR_ID_RE.match(v) for v in value):
        _fail(path, f"'{field}' must be a list of ADR ids like ADR-0013")


def _validate_revision(path: Path, data: dict) -> None:
    m = REVISION_PATH_RE.search(path.as_posix())
    lineage_no, revision_no, letter = m.group(1), int(m.group(2)), m.group(3)
    own_label = f"{revision_no}-{letter}" if letter else str(revision_no)
    if data["id"] != f"ADR-{lineage_no}":
        _fail(path, f"id '{data['id']}' doesn't match its directory (expected ADR-{lineage_no})")
    if data.get("revision") != revision_no or not _is_int(data.get("revision")):
        _fail(path, f"'revision' must be {revision_no}, matching its filename")
    if letter is None and "candidate" in data:
        _fail(path, "'candidate' is only valid on a revision-NNN-x.md file")
    if letter is not None and data.get("candidate") != letter:
        _fail(path, f"'candidate' must be '{letter}', matching its filename")
    if data.get("topic") not in TOPICS:
        _fail(path, f"topic '{data.get('topic')}' isn't one of {sorted(TOPICS)}")
    _require_text(path, data, "solution")
    _require_text(path, data, "summary")
    for field in ("supersedes", "superseded_by"):
        if field in data:
            label = ref_label(data[field])
            if label is None or int(label.split("-")[0]) == revision_no:
                _fail(path, f"'{field}' must name a revision in another generation of this lineage (like 0 or 1-b), not {own_label}")
    if data["status"] == "superseded" and "superseded_by" not in data:
        _fail(path, "status: superseded needs a 'superseded_by' revision")
    if "superseded_by" in data and data["status"] != "superseded":
        _fail(path, "'superseded_by' is only valid with status: superseded")
    if "narrows" in data and not (isinstance(data["narrows"], str) and ADR_ID_RE.match(data["narrows"])):
        _fail(path, "'narrows' must be a single ADR id like ADR-0015")
    _id_list(path, data, "related")
    _id_list(path, data, "former_ids")


def _validate_project(path: Path, data: dict) -> None:
    _require_text(path, data, "summary")
    if "blocked" in data and not isinstance(data["blocked"], bool):
        _fail(path, "'blocked' must be true or false")
    if data["status"] == "blocked":
        if "blocked" in data:
            _fail(path, "status: blocked is the legacy form; use a lifecycle status plus 'blocked: true'")
        if not data.get("blocked_reason"):
            _fail(path, "status: blocked needs a 'blocked_reason' field")
    elif data.get("blocked") is True and not data.get("blocked_reason"):
        _fail(path, "blocked: true needs a 'blocked_reason' field")
    for field, parent in (("super_project", None), ("track", "super_project"), ("phase", "track")):
        if field in data and not (isinstance(data[field], str) and SLUG_RE.match(data[field])):
            _fail(path, f"'{field}' must be a lowercase-hyphen slug")
        if field in data and parent and parent not in data:
            _fail(path, f"'{field}' needs '{parent}': a {field} belongs to one")
    if "decision" in data and not (isinstance(data["decision"], str) and REVISION_REF_RE.match(data["decision"])):
        _fail(path, "'decision' must be a single revision reference like ADR-0013/2")
    depends_on = data.get("depends_on", [])
    if not isinstance(depends_on, list):
        _fail(path, "'depends_on' must be a list")
    for dep in depends_on:
        if not (isinstance(dep, dict) and isinstance(dep.get("project"), str) and PROJECT_ID_RE.match(dep["project"])):
            _fail(path, "each 'depends_on' entry needs a 'project' id like PROJ-name")
        if not isinstance(dep.get("reason"), str) or not dep["reason"].strip():
            _fail(path, f"'depends_on' entry for {dep['project']} needs a 'reason' naming the concrete prerequisite")


def read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise SystemExit(f"{path}: missing frontmatter")
    data = yaml.safe_load(m.group(1)) or {}
    for required in ("id", "title", "type", "status"):
        if required not in data:
            raise SystemExit(f"{path}: frontmatter missing required field '{required}'")
    kind = doc_kind(path)
    if data["type"] != KIND_TYPE[kind]:
        raise SystemExit(f"{path}: type '{data['type']}' doesn't match its location (expected '{KIND_TYPE[kind]}')")
    if data["status"] not in VALID_STATUS[kind]:
        raise SystemExit(f"{path}: status '{data['status']}' isn't valid for type: {data['type']} here (expected one of {sorted(VALID_STATUS[kind])})")
    if kind == "adr-revision":
        _validate_revision(path, data)
    elif kind == "project":
        _validate_project(path, data)
    return data


def docs_in(dir_path: Path) -> list[Path]:
    return sorted(p for p in dir_path.glob("*.md") if p.name not in ("README.md", "TEMPLATE.md"))


@dataclass(frozen=True)
class Revision:
    path: Path
    number: int  # the generation
    fm: dict
    candidate: str | None = None  # a letter when competing solutions share the generation

    @property
    def status(self) -> str:
        return self.fm["status"]

    @property
    def label(self) -> str:
        return f"{self.number}-{self.candidate}" if self.candidate else str(self.number)


@dataclass(frozen=True)
class Lineage:
    number: str
    dir: Path
    revisions: tuple[Revision, ...]

    @property
    def id(self) -> str:
        return f"ADR-{self.number}"

    def get(self, ref: object) -> Revision | None:
        label = ref_label(ref)
        return next((r for r in self.revisions if r.label == label), None) if label is not None else None

    def current(self) -> Revision:
        """The revision a reader should treat as this problem's solution:
        the accepted (or retired) one, else the newest one still being
        worked, else the newest of whatever remains.
        """
        for statuses in (("accepted", "retired"), ("working", "approved")):
            matching = [r for r in self.revisions if r.status in statuses]
            if matching:
                return matching[-1]
        return self.revisions[-1]

    def pending_successors(self) -> list[Revision]:
        current = self.current()
        return [r for r in self.revisions if r.number > current.number and r.status in ("working", "approved")]


def load_lineages(root: Path = ROOT) -> list[Lineage]:
    decisions = root / "docs" / "decisions"
    if not decisions.is_dir():
        return []
    lineages = []
    for lineage_dir in sorted(p for p in decisions.iterdir() if p.is_dir() and LINEAGE_DIR_RE.match(p.name)):
        revisions = []
        for f in lineage_dir.glob("*.md"):
            m = REVISION_FILE_RE.match(f.name)
            if not m:
                raise SystemExit(f"{f}: lineage directories hold only revision-NNN.md and revision-NNN-x.md files")
            revisions.append(Revision(f, int(m.group(1)), read_frontmatter(f), m.group(2)))
        revisions.sort(key=lambda r: (r.number, r.candidate or ""))
        if not revisions:
            raise SystemExit(f"{lineage_dir}: lineage directory has no revision files")
        lineages.append(Lineage(lineage_dir.name[:4], lineage_dir, tuple(revisions)))
    return lineages
