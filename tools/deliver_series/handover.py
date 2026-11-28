"""What the session says to the maintainer when a series has passed: the layers, what to read, what was not checked, and the commands."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from land_series.replay import stopped_by

from deliver_series.build import Layer

# A change to one of these is to code that runs the checks, a hook, CI or the agent's own settings.
TOOLING_PREFIXES = (".githooks/", ".pre-commit-config.yaml", ".config/", ".github/", ".claude/", "tools/")
ROLE = re.compile(r"ansible/roles/([^/]+)/")

# `landing-a-series.md` gives these; a test holds them equal to its blocks.
SERIES_PROMPT = "read -r -p 'series file: ' series"
REPLAY_COMMAND = 'uv run python -m land_series "$series" --repo ..'
LAND_COMMAND = f"{REPLAY_COMMAND} --land"


def _layer_files(layer: Layer, paths: Mapping[str, list[str]]) -> list[str]:
    return [path for commit in layer.commits for path in paths[commit.sha]]


def stop_list(layers: Sequence[Layer], paths: Mapping[str, list[str]]) -> list[tuple[str, str, list[str]]]:
    """The commits on the stop list, as (layer id, slug, files) in landing order."""
    found = []
    for layer in layers:
        for layer_id, commit in zip(layer.ids(), layer.commits, strict=True):
            if files := stopped_by(paths[commit.sha]):
                found.append((layer_id, layer.plan.slug, files))
    return found


def tooling_layers(layers: Sequence[Layer], paths: Mapping[str, list[str]]) -> dict[str, list[str]]:
    """The layers that touch a hook, CI or tooling path, with those files."""
    return {
        f"{layer.number:04d} {layer.plan.slug}": sorted({path for path in _layer_files(layer, paths) if path.startswith(TOOLING_PREFIXES)})
        for layer in layers
        if any(path.startswith(TOOLING_PREFIXES) for path in _layer_files(layer, paths))
    }


def unverified_roles(layers: Sequence[Layer], paths: Mapping[str, list[str]]) -> list[str]:
    """The Ansible roles the series changes, whose Molecule scenarios no delivery runs."""
    return sorted({found.group(1) for layer in layers for path in _layer_files(layer, paths) if (found := ROLE.match(path))})


def render(series: Path, layers: Sequence[Layer], paths: Mapping[str, list[str]], skips: Mapping[str, str]) -> str:
    lines = [f"Series file: {series}", "", "Layers:"]
    for layer in layers:
        title = layer.plan.title or layer.commits[0].subject
        lines.append(f"- {layer.number:04d} {layer.plan.slug}: {title} ({len(layer.commits)} commit{'s' * (len(layer.commits) != 1)})")
    if stops := stop_list(layers, paths):
        lines += ["", "On the stop list (read each patch before accepting it):"]
        lines += [f"- {layer_id} {slug}: {', '.join(files)}" for layer_id, slug, files in stops]
    if touching := tooling_layers(layers, paths):
        lines += ["", "Touching a hook, CI or tooling path:"]
        lines += [f"- {name}: {', '.join(files)}" for name, files in touching.items()]
    lines += ["", "Not checked:"]
    lines += [f"- hook `{hook}` skipped: {reason}" for hook, reason in skips.items()]
    lines += [f"- Molecule for the role `{role}` was not run" for role in unverified_roles(layers, paths)]
    if not skips and not unverified_roles(layers, paths):
        lines.append("- nothing skipped; no Molecule scenario is run by a delivery")
    return "\n".join(lines)


def commands() -> str:
    """The maintainer's replay and `--land` commands, each in a block of its own."""
    blocks = [
        ["# paste alone; it waits for the series file's path, absolute or from tools/", SERIES_PROMPT],
        ["cd tools", REPLAY_COMMAND],
        [LAND_COMMAND],
    ]
    return "\n\n".join("```bash\n" + "\n".join(block) + "\n```" for block in blocks)
