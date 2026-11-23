"""Unit tests for doc_policy_flows.py: the gateway's zone policy names its flows and no doc
cites one by its number. Run via `uv run pytest tools/tests/ -v`.
"""

from __future__ import annotations

import pytest
from doc_scripts import doc_policy_flows as policy_flows

POLICY = "docs/topics/infra/tofu/opnsense-gateway.md"
TABLE = (
    "# Gateway\n\n## Zone policy\n\nIntro.\n\n"
    "| Flow | From | To |\n| :--- | :--- | :--- |\n"
    "| `operator-gateway` | Operator host | The gateway |\n"
    "| `cd-agent-gateway` | CD agent | The gateway |\n"
    "| `operator-vlan30-ssh` | Operator host | VLAN 30 host |\n\n"
    "## Zones\n\nOther.\n"
)


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def gateway(root):
    write(root, POLICY, TABLE)
    return root


class TestTheTable:
    def test_a_table_of_named_flows_is_fine(self, gateway):
        assert policy_flows.policy_flow_errors(gateway) == []

    def test_the_names_are_read_in_table_order(self, gateway):
        assert policy_flows.flow_names(gateway) == ["operator-gateway", "cd-agent-gateway", "operator-vlan30-ssh"]

    def test_a_tree_without_the_gateway_doc_has_nothing_to_check(self, root):
        write(root, "docs/topics/a.md", "Rows 7 and 12 of [it](opnsense-gateway.md#zone-policy).\n")
        assert policy_flows.policy_flow_errors(root) == []
        assert policy_flows.flow_names(root) == []

    @pytest.mark.parametrize("cell", ["7", "operator", "`operator`", "Operator-Gateway", "`Operator-Gateway`", "operator-gateway", ""])
    def test_a_first_cell_that_is_not_a_name_is_refused(self, root, cell):
        write(root, POLICY, TABLE.replace("`cd-agent-gateway`", cell or " "))
        [error] = policy_flows.policy_flow_errors(root)
        assert error.startswith(f"{POLICY}:10: the first cell is ")

    def test_a_name_used_twice_is_refused_and_names_the_first_use(self, root):
        write(root, POLICY, TABLE.replace("`cd-agent-gateway`", "`operator-gateway`"))
        [error] = policy_flows.policy_flow_errors(root)
        assert error == f"{POLICY}:10: the flow name operator-gateway is already used by line 9"

    def test_a_policy_section_with_no_table_is_refused(self, root):
        write(root, POLICY, "## Zone policy\n\nNo table yet.\n")
        [error] = policy_flows.policy_flow_errors(root)
        assert "has no table" in error

    def test_a_table_in_another_section_is_not_the_policy(self, root):
        write(root, POLICY, "## Zone policy\n\nText.\n\n## Other\n\n| Flow |\n| :--- |\n| 1 |\n")
        [error] = policy_flows.policy_flow_errors(root)
        assert "has no table" in error


class TestACitedName:
    def test_a_linked_name_that_is_in_the_table_is_fine(self, gateway):
        write(gateway, "docs/topics/a.md", "See [`operator-gateway`](infra/tofu/opnsense-gateway.md#zone-policy).\n")
        assert policy_flows.policy_flow_errors(gateway) == []

    def test_a_linked_name_that_is_not_in_the_table_is_refused(self, gateway):
        write(gateway, "docs/topics/a.md", "\nSee [`operator-nowhere`](infra/tofu/opnsense-gateway.md#zone-policy).\n")
        [error] = policy_flows.policy_flow_errors(gateway)
        assert error == "docs/topics/a.md:2: names the flow operator-nowhere, which is not in the zone policy's table"

    def test_a_bare_section_link_inside_the_gateway_doc_is_checked(self, root):
        write(root, POLICY, TABLE + "\nSee [`operator-nowhere`](#zone-policy) and [`operator-gateway`](#zone-policy).\n")
        [error] = policy_flows.policy_flow_errors(root)
        assert "operator-nowhere" in error

    def test_a_bare_section_link_in_another_doc_is_that_doc_s_own_section(self, gateway):
        write(gateway, "docs/topics/a.md", "[`not-a-flow`](#zone-policy) in [x](infra/tofu/opnsense-gateway.md).\n")
        assert policy_flows.policy_flow_errors(gateway) == []

    def test_a_code_span_with_no_link_is_not_a_citation(self, gateway):
        write(gateway, "docs/topics/a.md", "The `redeploy-storage` key, in [the gateway](infra/tofu/opnsense-gateway.md#zone-policy).\n")
        assert policy_flows.policy_flow_errors(gateway) == []


class TestANumberedRow:
    @pytest.mark.parametrize("text", ["rows 7 and 12", "Row 9", "row #3", "rows 2 and 3"])
    def test_a_row_number_in_a_doc_that_links_the_gateway_doc_is_refused(self, gateway, text):
        write(gateway, "docs/topics/a.md", f"Intro.\n\nThe flows ({text}) of [the gateway](infra/tofu/opnsense-gateway.md).\n")
        [error] = policy_flows.policy_flow_errors(gateway)
        assert error.startswith("docs/topics/a.md:3: cites a row of the zone policy by its number")

    def test_a_row_number_inside_the_gateway_doc_is_refused(self, root):
        write(root, POLICY, TABLE + "\nSame as row 9.\n")
        [error] = policy_flows.policy_flow_errors(root)
        assert error.startswith(f"{POLICY}:{len(TABLE.splitlines()) + 2}: cites a row")

    def test_a_row_number_in_a_doc_that_does_not_link_the_gateway_doc_is_another_table(self, gateway):
        write(gateway, "docs/topics/a.md", "Row 3 of the CSV is the header.\n")
        assert policy_flows.policy_flow_errors(gateway) == []

    def test_the_word_row_with_no_number_is_fine(self, gateway):
        write(gateway, "docs/topics/a.md", "Each row of [the table](infra/tofu/opnsense-gateway.md#zone-policy) is a flow.\n")
        assert policy_flows.policy_flow_errors(gateway) == []

    @pytest.mark.parametrize("rel", ["docs/decisions/0094-x/revision-000.md", "tools/tests/t.md", "docs/project-planning.md"])
    def test_the_places_that_keep_their_numbers_are_skipped(self, gateway, rel):
        write(gateway, rel, "Rows 1 to 17 of [the policy](../topics/infra/tofu/opnsense-gateway.md#zone-policy).\n")
        assert policy_flows.policy_flow_errors(gateway) == []
