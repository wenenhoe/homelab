---
id: EXP-opnsense-rule-drift-read
title: "How could the play tell a firewall rule it writes from one it must remove?"
type: exploration
status: open
summary: "What the collection returns for the rules a gateway holds, and by what the play decides that a rule is not its own."
topic: security-hardening
related: [ADR-0089]
---

# How could the play tell a firewall rule it writes from one it must remove?

ADR 0089 has the play keep the gateway's rules equal to its own, so a rule added by hand is reported under `--check --diff` and removed by a run. The play already does this for Unbound forwards by reading the list the gateway holds and removing what it does not write. This records what a scratch gateway at 26.1.11 showed for rules, and the ways to decide that a rule is not the play's.

## What a scratch gateway showed

- `oxlorg.opnsense.list` with `target: rule` returns the API's own rules as a list under `data`. A rule carries `uuid`, `description`, `sequence`, `enabled`, `interface` (a list), `action`, `protocol` and the source and destination fields. A port comes back as a number when it is one and as the alias name otherwise.
- After the play converged, the gateway held 46 rules: the guard rule, 24 zone-service rules, 5 direct-DNS denials, the 11 flow rules (4 of them disabled) and 5 Internet rules. Every one has a description, no two share one, and none is a rule the play does not write.
- The seed's legacy rule on the untagged LAN is not in the list, as the API path holds only its own rules.
- The play's `--check` reported no change with a hand-made rule present, so nothing notices one today.
- The rule module with `state: absent` and `match_fields: [description]` reports a change and a diff under `--check` and leaves the rule listed; a run removes it, and the list is then the same set as before.

## Options

- **By description.** The play builds the set of descriptions it writes, from the same lists its tasks loop over, and removes every listed rule whose description is not in it. The set has to hold the disabled rules too, and has to leave out a rule a switch turns off, which an `absent` task removes already. It costs a second place that names each rule, unless the tasks loop over one list.
- **By sequence band.** A rule is the play's own when its sequence is inside a band the play uses. It needs no description set, but a hand-made rule inside a band, or outside every band, is not what the check is for in either direction.
- **By a marker in the description.** Every rule the play writes carries a fixed prefix and only rules with it are candidates. It leaves a hand-made rule without the prefix alone, which is the opposite of what the stage needs.

## Leaning

By description. The guard rule is in the set, so it is never removed. The open part is how the set is built without a second list that drifts from the tasks, which is a question for the stage's design and not for the collection.
