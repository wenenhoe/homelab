"""Declared reliance between decisions (ADR 0080).

A revision's `relies_on:` says its reasoning holds only while another lineage's
boundary does. The reliant revision's state sets what the target must be: an
`approved` revision needs a revision of the target lineage that is `approved`
or `accepted`, an `accepted` one needs one that is `accepted`, and any other
state is not checked, since it is not claiming anything. Only declared reliance
is read, never `related:` or links in prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from doc_scripts.doc_frontmatter import ROOT, Lineage, Revision, load_lineages

# What the target lineage must hold, by the reliant revision's state.
REQUIRED_TARGET_STATES = {
    "approved": ("approved", "accepted"),
    "accepted": ("accepted",),
}


@dataclass(frozen=True)
class UnmetReliance:
    reliant: Revision
    root: Path
    target: str
    target_state: str  # the state of the target's current revision
    reason: str

    def message(self) -> str:
        rel = self.reliant.path.relative_to(self.root)
        return f"{rel} ({self.reliant.status}) relies on {self.target}, which is {self.target_state}: {self.reason}"


def unmet_reliances(root: Path = ROOT) -> list[UnmetReliance]:
    lineages = load_lineages(root)
    by_id: dict[str, Lineage] = {lineage.id: lineage for lineage in lineages}
    unmet = []
    for lineage in lineages:
        for rev in lineage.revisions:
            required = REQUIRED_TARGET_STATES.get(rev.status)
            if required is None:
                continue
            for reliance in rev.fm.get("relies_on", []):
                target = by_id.get(reliance["adr"])
                if target is None or any(r.status in required for r in target.revisions):
                    continue  # an unknown id is reported by lineage_errors
                unmet.append(UnmetReliance(rev, root, target.id, target.current().status, reliance["reason"]))
    return unmet


def reliance_warnings(root: Path = ROOT) -> list[str]:
    return [u.message() for u in unmet_reliances(root)]
