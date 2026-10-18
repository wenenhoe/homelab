"""Render one Jinja2 template to stdout: render_template.py TEMPLATE VARIABLES_JSON.

A variable the template uses and VARIABLES_JSON lacks is an error, not an empty
string. Block trimming and the kept trailing newline are the options Ansible's
template module renders with.
"""

import json
import sys
from pathlib import Path

from jinja2 import Environment, StrictUndefined


def render(template: Path, variables: dict) -> str:
    # The output is a shell script: HTML escaping would corrupt it, and Ansible does not escape either.
    environment = Environment(undefined=StrictUndefined, trim_blocks=True, keep_trailing_newline=True, autoescape=False)  # noqa: S701
    return environment.from_string(template.read_text()).render(variables)


if __name__ == "__main__":
    sys.stdout.write(render(Path(sys.argv[1]), json.loads(sys.argv[2])))
