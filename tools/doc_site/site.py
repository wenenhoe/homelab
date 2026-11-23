"""Builds the site: one page for each generated view, a home page and the assets they share."""

from __future__ import annotations

import base64
import hashlib
import html
import posixpath
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from doc_scripts.doc_frontmatter import GENERATED_VIEWS, REVISION_PATH_RE, ROOT, Lineage, docs_in, is_template, load_lineages, read_frontmatter
from doc_scripts.generate_doc_indexes import generated_blocks, intro_path
from doc_scripts.view_model import Block, Grid, Groups, Note, Table
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from doc_site import diagrams
from doc_site.diagrams import DiagramError, Draw, Drawn
from doc_site.documents import MARKER, Rendered, render
from doc_site.markup import BRANCH, REPO_URL, Anchors, Heading, UnsupportedMarkup, blocks, inline, link_resolver, status_key
from doc_site.summary import ROADMAP_COLUMNS, tiles

PACKAGE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class View:
    source: str  # the markdown view, from the repository root
    slug: str  # its directory on the site
    nav: str  # its label in the navigation


VIEWS = (
    View("docs/project-planning.md", "project-planning", "Planning"),
    View("docs/decision-index.md", "decision-index", "Decisions"),
    View("docs/topics/disaster-recovery/coverage.md", "dr-coverage", "DR coverage"),
)

# What the home page says about each entry of the navigation.
HOME = {
    "project-planning": "What is planned, building and waiting, and which decisions have no project yet.",
    "projects": "How projects work, and where each stage of a project stands.",
    "decision-index": "Every decision by number and by topic, the open ones and the superseded ones.",
    "topics": "How each part of the homelab is built, run and recovered.",
    "architecture": "Diagrams of the system as it runs: the fleet, DNS, authentication, secrets, backups and alerting.",
    "dr-coverage": "What each app has: where it runs, what is backed up, its record and its recovery tier.",
}

# The navigation, in order: the page each entry opens (a source path) and its slug and label.
NAV = (
    ("docs/project-planning.md", "project-planning", "Planning"),
    ("docs/projects/README.md", "projects", "Projects"),
    ("docs/decision-index.md", "decision-index", "Decisions"),
    ("docs/topics/README.md", "topics", "Topics"),
    ("docs/architecture/README.md", "architecture", "Architecture"),
    ("docs/topics/disaster-recovery/coverage.md", "dr-coverage", "DR coverage"),
)

# Pages that belong under another entry of the navigation: the decision pages are under Decisions, whose entry opens the index.
SECTIONS = {"decision-index": ("decisions",)}


@dataclass(frozen=True)
class Section:
    """A part of the site that opens on a list and has a README that says how it works: every page of it shows where it is in that part."""

    name: str
    prefix: str  # the slug that begins the pages of its documents
    landing: str  # the slug of the page that lists it, which its first crumb links to
    guide: str | None = None  # the address of its README from the site's root, when that is not the landing
    guide_label: str = ""


SECTION_LIST = (
    Section("Projects", "projects", "projects", "projects/#guide", "Guide to projects"),
    Section("Decisions", "decisions", "decision-index", "decisions/", "Guide to decisions"),
    Section("Topics", "topics", "topics"),
    Section("Architecture", "architecture", "architecture"),
)
PROJECT_ORDER = ("building", "de-risking", "not-started", "done")
PROJECT_STATUS = {"building": "Building", "de-risking": "De-risking", "not-started": "Not started", "done": "Done"}


def section_of(slug: str) -> Section | None:
    return next((s for s in SECTION_LIST if slug in (s.landing, s.prefix) or slug.startswith(f"{s.prefix}/")), None)


TITLES = ("Project", "Decision", "Problem", "App", "Exploration")
EYEBROWS = ("ADR", "Revision")
NO_VALUE = ("", "—", "(no initiative)")


def roles_of(headers: tuple[str, ...]) -> list[str]:
    """What each column is for on a card: the identifier and the status pill head it, the first
    name-like column is the title, and everything else is a labelled field."""
    roles: list[str] = []
    titled = False
    for header in headers:
        if header == "Status":
            roles.append("status")
        elif header in EYEBROWS or (header == "Initiative" and "Project" in headers):
            roles.append("eyebrow")
        elif (header in TITLES or header == "Initiative") and not titled:
            roles.append("title")
            titled = True
        else:
            roles.append("field")
    return roles


_LINK = r"\[`(?P<name>[^`]+?)(?:\.md)?`\]\((?P<target>[^)\s]+)\)(?: \(unblocks (?P<count>\d+)\))?"
_CHIP = re.compile(_LINK)


def _chips(cell: str, resolve) -> str | None:
    """A roadmap cell, a comma-separated list of project links each with an optional `(unblocks N)`, as one chip for each project. None when
    the cell is anything else, so it is rendered as text and nothing is lost."""
    links = list(_CHIP.finditer(cell))
    if not links or ", ".join(link.group(0) for link in links) != cell:
        return None
    chips = []
    for link in links:
        href = html.escape(resolve(link["target"]), quote=True)
        badge = f'<span class="badge">unblocks {link["count"]}</span>' if link["count"] else ""
        chips.append(f'<a class="chip" href="{href}">{html.escape(link["name"], quote=False)}{badge}</a>')
    return f'<div class="chips">{"".join(chips)}</div>'


def _table(table: Table, resolve, chips: tuple[str, ...] = ()) -> str:
    roles = roles_of(table.headers)
    head = "".join(f"<th>{inline(h, resolve)}</th>" for h in table.headers)
    body = []
    for row in table.rows:
        cells = []
        key = ""
        for header, role, cell in zip(table.headers, roles, row, strict=True):
            text = (_chips(cell, resolve) if header in chips else None) or inline(cell, resolve)
            classes = [role] + (["none"] if cell in NO_VALUE else []) + ([f"col-{re.sub(r'[^a-z]+', '-', header.lower())}"] if header in chips else [])
            if role == "status" and cell not in NO_VALUE:
                key = status_key(text)
                text = f'<span class="pill s-{key}">{text}</span>'
            cells.append(f'<td class="{" ".join(classes)}" data-label="{inline(header, resolve)}">{text}</td>')
        has_eyebrow = any(role == "eyebrow" and cell not in NO_VALUE for role, cell in zip(roles, row, strict=True))
        classes = ([f"s-{key}"] if key else []) + ([] if has_eyebrow else ["ne"])
        body.append(f'<tr class="{" ".join(classes)}">{"".join(cells)}</tr>')
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _grid(grid: Grid, resolve) -> str:
    """Numbers ten to a row, each row labelled. A list and not a table, so a narrow screen can break a row in two without
    a sideways scroll."""
    rows = []
    for label, cells in grid.rows:
        items = "".join(f'<li class="n-{cell.kind}">{inline(cell.markdown, resolve)}</li>' for cell in cells)
        rows.append(f'<div class="num-row"><span class="num-label">{label}</span><ol>{items}</ol></div>')
    return f'<div class="numbers">{"".join(rows)}</div>'


def _block(block: Block, resolve, anchors: Anchors, headings: list[Heading], chips: tuple[str, ...] = ()) -> str:
    if isinstance(block, Note):
        return f'<p class="note">{inline(block.text, resolve)}</p>'
    if isinstance(block, Table):
        return _table(block, resolve, chips)
    if isinstance(block, Grid):
        return _grid(block, resolve)
    if isinstance(block, Groups):
        tabs = []
        for title, table in block.items:
            anchor = anchors.of(title)
            headings.append(Heading(3, anchor, title))
            label = inline(title, resolve)
            link = f'<a class="tab-link" href="#{anchor}">{label}</a>'
            tabs.append(f'<div class="tab">{link}<div class="panel"><h3 id="{anchor}">{label}</h3>{_table(table, resolve)}</div></div>')
        return f'<div class="tabs">{"".join(tabs)}</div>'
    raise TypeError(f"unknown block {block!r}")


# A document page with this many headings in its menu lists them on the page.
CONTENTS_MIN = 4
CONTENTS_ID = "on-this-page"
# The documents whose `##` groups are tabs over a list of links. A rule names each, so no other document is ever tabbed by inference.
TABBED_DOCUMENTS = frozenset({"docs/topics/README.md"})
H2 = re.compile(r'<h2 id="([^"]+)">(.*?)</h2>', re.DOTALL)


def _contents(headings: Sequence[Heading]) -> str:
    """The list of a page's headings, shown on the page. It is open in the markup so that it needs no script, which closes it on a narrow screen."""
    sub = ' class="sub"'
    items = "".join(f'<li><a href="#{h.id}"{sub if h.level == 3 else ""}>{html.escape(h.text)}</a></li>' for h in headings)
    return f'<nav class="toc" id="{CONTENTS_ID}" aria-label="On this page"><details open><summary>On this page</summary><ol>{items}</ol></details></nav>'


def _links_back(html: str) -> str:
    """Each `##` heading of `html` with a link back to the contents list."""
    return H2.sub(lambda m: f'<h2 id="{m[1]}">{m[2]} <a class="up" href="#{CONTENTS_ID}">&#8593; On this page</a></h2>', html)


def _tabbed(html: str) -> str:
    """The `##` groups of `html` as tabs, each a link beside its panel, under a filter. What comes before the first group stays above
    them, and a page with no group is returned as it is."""
    parts = re.split(r"(?=<h2 id=)", html)
    if len(parts) < 2:
        return html
    tabs = []
    for part in parts[1:]:
        heading = H2.match(part)
        tabs.append(f'<div class="tab"><a class="tab-link" href="#{heading[1]}">{heading[2]}</a><div class="panel">{part}</div></div>')
    box = '<div class="filter"><input id="q" type="search" placeholder="Filter links" aria-label="Filter links"></div>\n'
    return f'{parts[0]}{box}<div class="tabs">{"".join(tabs)}</div>\n'


def _title_and_intro(text: str, view: str) -> tuple[str, str]:
    """The `# Title` line and the prose after it, from the view's introduction file. A `## ` section in that
    file is refused: the page is built from the rows, so a hand-written section would be lost."""
    lines = text.splitlines()
    heading = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if heading is None:
        raise UnsupportedMarkup(f"{view} has no `# ` title")
    if any(line.startswith("## ") for line in lines):
        raise UnsupportedMarkup(f"{view} has a `## ` section; the sections of a view are generated")
    return lines[heading][2:].strip(), "\n".join(lines[heading + 1 :])


def split_intro(paragraphs: list[str], headings: list[str]) -> tuple[list[str], dict[str, str], list[str]]:
    """An introduction's paragraphs as markdown, sorted for the page: the lede that opens it, the caption of each section, and the rest.

    A paragraph that opens with a section's name in bold (`**Roadmap** has one row...`) is that section's caption, and the page puts it
    under the section's heading, where it explains what is there. The first paragraph that is not a caption is the lede. Every other
    paragraph, such as a definition of a column that several sections share, goes in a legend the reader opens. A section renamed
    without its paragraph does not lose the paragraph: it moves to the legend."""
    captions: dict[str, str] = {}
    rest: list[str] = []
    for paragraph in paragraphs:
        lead = re.match(r"\*\*([^*]+)\*\*", paragraph)
        if lead and lead[1] in headings and lead[1] not in captions:
            captions[lead[1]] = paragraph
        else:
            rest.append(paragraph)
    return rest[:1], captions, rest[1:]


@dataclass(frozen=True)
class Document:
    source: str  # the markdown file, from the repository root
    slug: str  # its directory on the site: `projects/<name>`, `topics/<path>`
    front: dict  # its front matter, empty for a document that has none

    @property
    def depth(self) -> int:
        """How many directories under the site's root its page is: none for the home page, which `docs/README.md` is."""
        return self.slug.count("/") + 1 if self.slug else 0


def _slug(source: str) -> str:
    """A document's directory on the site: its path under `docs/` without `.md`, and a README is its directory's page, so
    `docs/README.md` is the home page and its slug is empty."""
    path = source.removeprefix("docs/").removesuffix(".md")
    return "" if path == "README" else path.removesuffix("/README")


def _documents(root: Path, lineages: list[Lineage]) -> list[Document]:
    """The documents with a page of their own: the projects, the topic docs, the decision revisions and the architecture docs, with the README of
    each directory that has one and the README of `docs/`, which is the home page."""
    projects = [(path, read_frontmatter(path)) for path in docs_in(root / "docs/projects")]
    decisions = [(revision.path, revision.fm) for lineage in lineages for revision in lineage.revisions]
    decisions += [(path, {}) for path in sorted((root / "docs/decisions").glob("*.md")) if not is_template(path.name)]
    topics = sorted(
        path for path in (root / "docs/topics").rglob("*.md") if not is_template(path.name) and path.relative_to(root).as_posix() not in GENERATED_VIEWS
    )
    found = [(path, front) for path, front in projects + decisions] + [(path, {}) for path in topics]
    found += [(path, {}) for path in sorted((root / "docs/architecture").glob("*.md")) if not is_template(path.name)]
    found += [(root / "docs/projects/README.md", {}), (root / "docs/README.md", {})]
    documents = []
    for path, front in found:
        source = path.relative_to(root).as_posix()
        documents.append(Document(source, _slug(source), front))
    return sorted(documents, key=lambda document: document.source)


def _page_addresses(targets: dict[str, str], depth: int) -> dict[str, str]:
    """Each page's address from a page `depth` directories under the site's root; `targets` maps a source path to its directory."""
    return {source: f"{'../' * depth}{slug}/" if slug else "../" * depth or "./" for source, slug in targets.items()}


def _figure(drawn: Drawn) -> str:
    """A diagram in both renderings; the stylesheet shows the one that goes with the reader's colour scheme."""
    return f'<figure class="diagram"><div class="light">{drawn.light}</div><div class="dark">{drawn.dark}</div></figure>'


def _targets(documents: list[Document]) -> dict[str, str]:
    return {view.source: view.slug for view in VIEWS} | {document.source: document.slug for document in documents}


def _link(document: Document, source: str, text: str, resolve) -> str:
    """`text` as a link to the page of the file `source` (a path from the repository root), from the page of `document`."""
    href = resolve(posixpath.relpath(source, posixpath.dirname(document.source)))
    return f'<a href="{html.escape(href, quote=True)}">{html.escape(text, quote=False)}</a>'


def _pill(status: str) -> str:
    return f'<span class="pill s-{status_key(status)}">{html.escape(status)}</span>'


def _lineage_strip(document: Document, lineages: dict[str, Lineage], root: Path, resolve) -> str:
    """Every revision of the lineage of a decision page, in order, each with its state, the current one and the one being read marked. A
    lineage of one revision has no strip."""
    lineage = lineages[document.front["id"]]
    if len(lineage.revisions) < 2:
        return ""
    current, here = lineage.current(), root / document.source
    items = []
    for revision in lineage.revisions:
        text = f"revision {revision.label} ({revision.fm['short']})"
        classes = " ".join(name for name, on in (("here", revision.path == here), ("current", revision is current)) if on)
        body = html.escape(text) if revision.path == here else _link(document, revision.path.relative_to(root).as_posix(), text, resolve)
        marks = "".join(f'<span class="mark">{mark}</span>' for mark, on in (("current", revision is current), ("this page", revision.path == here)) if on)
        items.append(f'<li class="{classes}">{body}{_pill(revision.fm["status"])}{marks}</li>')
    return f'<nav class="lineage" aria-label="Revisions of this decision"><h2>Revisions</h2><ol>{"".join(items)}</ol></nav>\n'


def _pager(document: Document, lineage_list: list[Lineage], root: Path, resolve) -> str:
    """Links to the decisions before and after this one by number, each at its current revision."""
    ordered = sorted(lineage_list, key=lambda lineage: lineage.number)
    index = next(i for i, lineage in enumerate(ordered) if lineage.id == document.front["id"])
    links = []
    for side, other in (("prev", ordered[index - 1] if index else None), ("next", ordered[index + 1] if index + 1 < len(ordered) else None)):
        if other is not None:
            current = other.current()
            arrow = f"\u2190 ADR {other.number}" if side == "prev" else f"ADR {other.number} \u2192"
            link = _link(document, current.path.relative_to(root).as_posix(), arrow, resolve)
            links.append(f'<span class="{side}">{link}<span class="name">{html.escape(current.fm["short"])}</span></span>')
    return f'<nav class="pager" aria-label="Neighbouring decisions">{"".join(links)}</nav>\n' if links else ""


def _project_facts(document: Document, documents: list[Document], resolve) -> list[dict]:
    """The header of a project page, from its front matter: what a reader looks at before the body."""
    front = document.front
    by_id = {other.front["id"]: other for other in documents if other.source.startswith("docs/projects/") and other.front}
    waits = [by_id[d["project"]] for d in front.get("depends_on", []) if d["project"] in by_id]
    facts = [{"label": "Status", "html": _pill(front["status"])}]
    if front.get("blocked"):
        facts.append({"label": "Blocked", "html": "yes"})
    if front.get("super_project"):
        facts.append({"label": "Part of", "html": f"<code>{html.escape(front['super_project'])}</code>"})
    if front.get("decision"):
        facts.append({"label": "Decision", "html": f"<code>{html.escape(front['decision'])}</code>"})
    if waits:
        links = ", ".join(_link(document, other.source, Path(other.source).stem, resolve) for other in waits)
        facts.append({"label": "Waits on", "html": links})
    return facts


def _decision_facts(document: Document, documents: list[Document], lineages: dict[str, Lineage], root: Path, resolve) -> tuple[list[dict], str]:
    """The header of a decision revision, from its front matter, and the notice a superseded one carries: its state, what it replaces or is
    replaced by, what it relies on and which projects implement it. A lineage that is not in the tree (a removed one) is named, not linked."""
    front = document.front
    lineage = lineages[front["id"]]
    number = front["id"].removeprefix("ADR-")
    label = next(revision.label for revision in lineage.revisions if revision.path == root / document.source)

    def revision_link(revision) -> str:
        text = f"revision {revision.label} ({revision.fm['short']})"
        return _link(document, revision.path.relative_to(root).as_posix(), text, resolve)

    def lineage_link(adr: str) -> str:
        other = lineages.get(adr)
        if other is None:
            return html.escape(f"ADR {adr.removeprefix('ADR-')}")
        current = other.current()
        return _link(document, current.path.relative_to(root).as_posix(), f"ADR {other.number} ({current.fm['short']})", resolve)

    facts = [
        {"label": "Record", "html": f"ADR {number}, revision {label}"},
        {"label": "State", "html": _pill(front["status"])},
    ]
    if front.get("weight") == "light":
        facts.append({"label": "Weight", "html": "light"})
    notice = ""
    for field, name in (("supersedes", "Supersedes"), ("superseded_by", "Superseded by")):
        target = lineage.get(front[field]) if field in front else None
        if target is not None:
            facts.append({"label": name, "html": revision_link(target)})
            if field == "superseded_by":
                notice = f"This revision is superseded by {revision_link(target)}. It is kept as the record of what was decided then."
    if front.get("narrows"):
        facts.append({"label": "Narrows", "html": lineage_link(front["narrows"])})
    if front.get("relies_on"):
        items = "".join(
            f'<span class="rely">{lineage_link(r["adr"])}<span class="why">{html.escape(r["reason"], quote=False)}</span></span>' for r in front["relies_on"]
        )
        facts.append({"label": "Relies on", "html": items})
    if front.get("related"):
        facts.append({"label": "Related", "html": ", ".join(lineage_link(adr) for adr in front["related"])})
    reference = f"{front['id']}/{label}"
    implementing = [
        other
        for other in documents
        if other.source.startswith("docs/projects/") and other.front and reference in (other.front.get("decision"), *other.front.get("also_implements", []))
    ]
    if implementing:
        links = ", ".join(_link(document, other.source, Path(other.source).stem, resolve) for other in implementing)
        facts.append({"label": "Implemented by", "html": links})
    return facts, notice


def _cell(text: str) -> str:
    """`text` as a cell of a table that `_table` reads: its `|` escaped."""
    return text.replace("|", "\\|")


def _project_list(documents: list[Document]) -> Table:
    """The projects as rows, the building ones first: what a reader of the projects section looks for before the rules."""
    projects = sorted(
        (d for d in documents if d.source.startswith("docs/projects/") and d.front),
        key=lambda d: (PROJECT_ORDER.index(d.front["status"]), d.source),
    )
    rows = tuple(
        (
            f"[`{Path(d.source).stem}`]({Path(d.source).name})",
            PROJECT_STATUS[d.front["status"]],
            d.front.get("super_project", "(no initiative)"),
            _cell(d.front.get("summary", "")),
        )
        for d in projects
    )
    return Table(("Project", "Status", "Initiative", "Summary"), (":---",) * 4, rows)


def _crumbs(document: Document, title: str, base: str, lineages: dict[str, Lineage], root: Path, topic_groups: set[str]) -> dict | None:
    """Where a document's page is in its section: the section, what holds the page, the page, and the link to the section's README."""
    section = section_of(document.slug)
    if section is None:
        return None
    landing = f"{base}{section.landing}/"
    source = document.source
    if document.slug == section.landing:
        tail: list[tuple[str, str | None]] = []
    elif source == "docs/decisions/README.md":
        tail = [("Guide", None)]
    elif REVISION_PATH_RE.search(source):
        lineage = lineages[document.front["id"]]
        label = next(r.label for r in lineage.revisions if r.path == root / source)
        tail = [(f"ADR {lineage.number}", None), (f"revision {label}", None)]
    elif section.name == "Projects":
        tail = [(Path(source).stem, None)]
    elif section.name == "Topics" and source.count("/") >= 3:
        group = source.split("/")[2]
        tail = [(group, f"{base}topics/#{group}" if group in topic_groups else None), (title, None)]
    else:
        tail = [(title, None)]
    items = [{"label": section.name, "href": landing if tail else None}] + [{"label": label, "href": href} for label, href in tail]
    guide = section.guide and f"{base}{section.guide}" if source != "docs/decisions/README.md" else None
    return {"trail": items, "guide": guide, "guide_label": section.guide_label}


def integrity(data: bytes) -> str:
    """The `integrity` attribute value (Subresource Integrity, sha384) for `data`."""
    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode("ascii")


@dataclass(frozen=True)
class Stamp:
    """The commit a site is built from, for the footer: a reader compares it with `main` to tell a page the CDN has not refreshed."""

    sha: str  # the full 40-hex commit id
    date: str  # the commit's date, ISO 8601 with an offset

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", self.sha):
            raise ValueError(f"not a full commit id: {self.sha!r}")
        datetime.fromisoformat(self.date)

    @property
    def short(self) -> str:
        return self.sha[:7]

    @property
    def url(self) -> str:
        return f"{REPO_URL}/commit/{self.sha}"

    @property
    def label(self) -> str:
        return datetime.fromisoformat(self.date).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def fingerprinted(name: str, data: bytes) -> str:
    """`assets/site.css` -> `assets/site.<first ten hex of its sha256>.css`. A page and the file it names change together, so a cache that
    holds the old page never pairs it with the new file, nor the new page with the old file (which, for the stylesheet, its integrity
    attribute would refuse)."""
    stem, dot, extension = name.rpartition(".")
    return f"assets/{stem}.{hashlib.sha256(data).hexdigest()[:10]}{dot}{extension}"


def build(root: Path = ROOT, stamp: Stamp | None = None, draw: Draw = diagrams.draw) -> dict[str, bytes]:
    """Every file of the site, by its path under the site's root. Reads only the tree and the stamp it is given, and the bundle that `draw` runs."""
    env = Environment(loader=FileSystemLoader(PACKAGE / "templates"), autoescape=True, undefined=StrictUndefined, keep_trailing_newline=True)
    generated = generated_blocks(root)
    stylesheet = (PACKAGE / "vendor/simple.min.css").read_bytes()
    sri = integrity(stylesheet)
    assets = {
        "simple_css": ("simple.css", stylesheet),
        "site_css": ("site.css", (PACKAGE / "assets/site.css").read_bytes()),
        "site_js": ("site.js", (PACKAGE / "assets/site.js").read_bytes()),
    }
    urls = {key: fingerprinted(name, data) for key, (name, data) in assets.items()}
    files: dict[str, bytes] = {urls[key]: data for key, (_, data) in assets.items()}
    files["assets/simple-licence.txt"] = (PACKAGE / "vendor/simple.LICENSE").read_bytes()

    lineage_list = load_lineages(root)
    lineages = {lineage.id: lineage for lineage in lineage_list}
    documents = _documents(root, lineage_list)
    targets = _targets(documents)

    def nav(slug: str | None, depth: int) -> list[dict]:
        pages = _page_addresses(targets, depth)
        return [
            {
                "href": pages[source],
                "label": label,
                "current": slug is not None and any(slug == own or slug.startswith(f"{own}/") for own in (page, *SECTIONS.get(page, ()))),
            }
            for source, page, label in NAV
            if source in pages
        ]

    for view in VIEWS:
        title, intro = _title_and_intro((root / intro_path(view.source)).read_text(encoding="utf-8"), intro_path(view.source))
        resolve = link_resolver(view.source, _page_addresses(targets, 1), lambda path: (root / path).is_dir())
        anchors = Anchors()
        headings = [Heading(1, anchors.of(title), title)]
        own = [g for g in generated if g.view == view.source]
        lede, captions, legend = split_intro(blocks(intro), [g.heading for g in own])
        sections = []
        counted: dict[str, tuple[str, Block]] = {}
        for item in own:
            anchor = anchors.of(item.heading)
            counted[item.heading] = (anchor, item.block)
            headings.append(Heading(2, anchor, item.heading))
            caption = inline(captions[item.heading], resolve) if item.heading in captions else ""
            sections.append(
                {
                    "id": anchor,
                    "title": item.heading,
                    "caption": caption,
                    "html": _block(item.block, resolve, anchors, headings, ROADMAP_COLUMNS if item.heading == "Roadmap" else ()),
                }
            )
        files[f"{view.slug}/index.html"] = (
            env.get_template("page.html.j2")
            .render(
                title=title,
                title_id=headings[0].id,
                tiles=tiles(view.slug, counted),
                lede=[inline(paragraph, resolve) for paragraph in lede],
                legend=[inline(paragraph, resolve) for paragraph in legend],
                sections=sections,
                headings=headings[1:],
                crumbs=_crumbs(Document(view.source, view.slug, {}), title, "../", lineages, root, set()),
                nav=nav(view.slug, 1),
                base="../",
                home="../",
                sri=sri,
                assets=urls,
                stamp=stamp,
            )
            .encode("utf-8")
        )
    pages: list[tuple[Document, Rendered]] = []
    readme: dict | None = None
    for document in documents:
        resolve = link_resolver(document.source, _page_addresses(targets, document.depth), lambda path: (root / path).is_dir())
        pages.append((document, render((root / document.source).read_text(encoding="utf-8"), resolve, document.source)))
    topic_groups = {h.id for document, page in pages if document.source == "docs/topics/README.md" for h in page.headings}
    sources = [(document, diagram) for document, page in pages for diagram in page.diagrams]
    try:
        drawn = iter(draw([diagram.code for _, diagram in sources]))
    except DiagramError as error:
        index = int(re.match(r"diagram (\d+)", str(error))[1]) if re.match(r"diagram (\d+)", str(error)) else 0
        document, diagram = sources[index]
        raise DiagramError(f"{document.source}:{diagram.line}: {re.sub(r'^diagram \d+: ', '', str(error))}") from error
    for document, page in pages:
        body = page.html
        for number in range(len(page.diagrams)):
            body = body.replace(MARKER.format(number), _figure(next(drawn)))
        resolve = link_resolver(document.source, _page_addresses(targets, document.depth), lambda path: (root / path).is_dir())
        revision_page = bool(REVISION_PATH_RE.search(document.source))
        if revision_page:
            facts, notice = _decision_facts(document, documents, lineages, root, resolve)
        else:
            facts, notice = (_project_facts(document, documents, resolve) if document.source.startswith("docs/projects/") and document.front else []), ""
        base = "../" * document.depth
        lead, pager, headings = "", "", page.headings
        if revision_page:
            lead, pager = _lineage_strip(document, lineages, root, resolve), _pager(document, lineage_list, root, resolve)
        if document.source == "docs/projects/README.md":
            if {"project-list", "guide"} & {h.id for h in page.headings}:
                raise ValueError(f"{document.source} has a heading with the anchor of the project list or of the guide")
            table = _table(_project_list(documents), resolve)
            lead = f'<section id="project-list"><h2>The projects</h2>{table}</section>\n<h2 id="guide">Guide to projects</h2>\n'
            headings = (Heading(2, "project-list", "The projects"), Heading(2, "guide", "Guide to projects"), *page.headings)
        contents = ""
        if document.source in TABBED_DOCUMENTS:
            body = _tabbed(body)
        elif document.slug and len(headings) >= CONTENTS_MIN:
            if CONTENTS_ID in {h.id for h in headings}:
                raise ValueError(f"{document.source} has a heading with the anchor of the list of headings")
            contents, lead, body = _contents(headings), _links_back(lead), _links_back(body)
        if not document.slug:
            readme = {
                "title": page.title,
                "id": page.title_id,
                "body": body,
                "headings": page.headings,
                "source_url": f"{REPO_URL}/blob/{BRANCH}/{document.source}",
            }
            continue
        files[f"{document.slug}/index.html"] = (
            env.get_template("document.html.j2")
            .render(
                title=page.title,
                title_id=page.title_id,
                summary=document.front.get("summary", ""),
                facts=facts,
                notice=notice,
                lead=lead,
                pager=pager,
                crumbs=_crumbs(document, page.title, base, lineages, root, topic_groups),
                body=body,
                contents=contents,
                headings=headings,
                source_url=f"{REPO_URL}/blob/{BRANCH}/{document.source}",
                nav=nav(document.slug, document.depth),
                base=base,
                home=base,
                sri=sri,
                assets=urls,
                stamp=stamp,
            )
            .encode("utf-8")
        )
    files["index.html"] = (
        env.get_template("home.html.j2")
        .render(
            views=[{"href": f"{slug}/", "label": label, "blurb": HOME[slug]} for source, slug, label in NAV if source in targets],
            readme=readme,
            nav=nav(None, 0),
            base="",
            home="",
            sri=sri,
            assets=urls,
            stamp=stamp,
        )
        .encode("utf-8")
    )
    return files


def page_anchors(root: Path = ROOT) -> dict[str, set[str]]:
    """The ids of each page's headings, its sections and its list of headings, by its slug (`""` for the home page): what a link to the site can
    name after the `#`."""
    built = build(root, draw=diagrams.skip)
    pages = {"": "index.html"} | {path.removesuffix("/index.html"): path for path in built if path.endswith("/index.html")}
    return {slug: set(re.findall(r'<(?:h[1-6]|section|nav)\b[^>]*? id="([^"]+)"', built[path].decode())) for slug, path in pages.items()}


def write(out: Path, root: Path = ROOT, stamp: Stamp | None = None) -> list[str]:
    """Writes the site into `out`, which must be empty or absent. Returns the paths written."""
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    files = build(root, stamp)
    for relative, data in files.items():
        path = out / posixpath.normpath(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return sorted(files)
