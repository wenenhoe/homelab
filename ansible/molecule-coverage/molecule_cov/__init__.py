"""Library backing molecule-coverage's CLI (see ../README.md).

Split into inventory.py (static task scanning), aggregate.py (JSONL ->
coverage stats), and report.py (formatting) so each is independently
importable and testable. cli.py wires them into the `inventory`/`report`
subcommands.
"""
