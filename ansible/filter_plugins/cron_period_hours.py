"""cron_period_hours: derive a freshness threshold from a cron expression.

backup_agent's own per-app cron (app_registry's `backup.cron`, defaulting
to offsite_backup_cron) is the one thing that actually determines how
often an app's backup runs. A separately hand-set freshness threshold can
drift from it the moment the cron changes and nobody remembers to update
both — this filter makes that structurally impossible by computing the
threshold directly from the cron string every time, so there is nothing
second to keep in sync.

Returns the LONGEST gap (in whole hours, rounded up) between two
consecutive firings within a rolling window from a fixed, deterministic
reference point - not the average interval. A plain daily cron has one
constant 24h gap either way, but a "weekdays only" cron has a 72h gap
over the weekend that an average would hide, and a freshness check must
tolerate the worst case, not the typical one. The reference point is a
fixed date (not "now"), so the same cron string always renders the same
value - required for Ansible's idempotence check (see
docs/molecule-testing.md), which a "now"-dependent value would fail
every single run.
"""

from __future__ import annotations

import datetime
import math

try:
    from croniter import croniter
except ImportError as exc:  # pragma: no cover - surfaced as a clear Jinja error instead
    raise ImportError(
        "cron_period_hours needs the 'croniter' package on the controller (pyproject.toml's own dependencies) - it is not installed here."
    ) from exc

# A fixed, arbitrary Monday - deterministic across every run and every
# controller, and far enough from any DST transition edge case in any
# timezone this project's controller might run in.
_REFERENCE = datetime.datetime(2024, 1, 1)

# Long enough to always span at least one full weekly cycle (the
# longest realistic gap this repo's cron patterns produce - see the
# "weekdays only" example above), short enough that even a very
# frequent cron doesn't force an enormous number of croniter calls.
_WINDOW_DAYS = 8


def cron_period_hours(cron_expr: str) -> int:
    """The worst-case gap, in whole hours (rounded up, minimum 1), between
    two consecutive firings of `cron_expr` within a fixed rolling window.
    """
    itr = croniter(cron_expr, _REFERENCE)
    times = [_REFERENCE]
    window_end = _REFERENCE + datetime.timedelta(days=_WINDOW_DAYS)
    # Keeps calling get_next() past window_end if needed, so an
    # infrequent cron (e.g. monthly) still yields at least one real gap
    # instead of a window artificially cut short before its first firing.
    while times[-1] < window_end:
        times.append(itr.get_next(datetime.datetime))
    gaps_hours = [(times[i + 1] - times[i]).total_seconds() / 3600 for i in range(len(times) - 1)]
    return max(1, math.ceil(max(gaps_hours)))


class FilterModule:
    def filters(self):
        return {"cron_period_hours": cron_period_hours}
