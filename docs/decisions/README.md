# Architecture Decision Records

A short record of *why* a specific design was chosen when the reasoning
is non-obvious, contested, or has a real alternative someone could
reasonably ask "why not X instead?" about. Not a changelog and not a
bug log — a fixed bug belongs in the doc it affects (stated as current
behavior) or in the PR/commit that fixed it, not here.

Write one when a decision:

- trades off two real options and the choice isn't obvious from the
  code alone (e.g. accepting a security gap because the alternative
  isn't available on a given platform)
- would be expensive to reverse, or someone new to the repo would
  otherwise have to reconstruct by reading old commits/PRs
- is still open (a known gap, tracked but not yet resolved)

Use [`TEMPLATE.md`](TEMPLATE.md) for new entries. Number sequentially;
never renumber or delete a superseded one — mark it `Superseded by
000N` instead, so old links keep resolving.
