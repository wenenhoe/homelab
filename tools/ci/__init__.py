"""CI logic the workflows call as Python modules, not inline shell: what a PR's diff
needs tested (`ci.scope`), and the checks and helpers the workflows call.
Each submodule is a domain; the workflows run them as
`cd tools && uv run python -m ci.<domain>.<module>`.
"""
