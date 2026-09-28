"""CI logic that used to live inline in workflows or bash: what a PR's diff
needs tested (`ci.scope`), and the checks and helpers the workflows call.
Each submodule is a domain; the workflows run them as
`cd tools && uv run python -m ci.<domain>.<module>`.
"""
