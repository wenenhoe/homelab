# Removed decision numbers

A lineage that held an accepted or superseded revision leaves the tree only on
the record: merged into another lineage, which lists its number in
`former_ids`, or demoted to a topic doc or dropped, which is listed here. A
number is never reused, so a listed number can never be a lineage again.
[`check_accepted_records.py`](../../tools/doc_scripts/check_accepted_records.py)
fails a change that removes one otherwise, and the drift check fails a number
listed here that a lineage holds.

| ADR | Fate | Where it went |
| :--- | :--- | :--- |
