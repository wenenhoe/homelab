"""Unit tests for filter_plugins/gpg_keys.py.

The samples are the output of `gpg --show-keys --with-colons` (GnuPG 2.4.4) on
throwaway keys, cut to the records the filter reads.
"""

from __future__ import annotations

import gpg_keys
import pytest
from ansible.errors import AnsibleFilterError

gpg_primary_fingerprints = gpg_keys.gpg_primary_fingerprints

PRIMARY = "AE623D99072E9AC03986184308958DCF2CE44379"
SUBKEY = "806D48797728514C9D2B9A944F58E9D28076F0F8"
OTHER = "3905C229861DC33F62ED90E279589F9D49F88957"

ONE_KEY_WITH_SUBKEY = f"""\
pub:-:2048:1:08958DCF2CE44379:1793702244:::-:::scESC::::::23::0:
fpr:::::::::{PRIMARY}:
uid:-::::1793702244::8C92211FA263BEF2FAF9C60DA7D394460A7FE301::Test Signer <t@example.invalid>:
sub:-:2048:1:4F58E9D28076F0F8:1793702244::::::e::::::23:
fpr:::::::::{SUBKEY}:
"""

TWO_KEYS = (
    ONE_KEY_WITH_SUBKEY
    + f"""\
pub:-:2048:1:79589F9D49F88957:1793702244:::-:::scSC::::::23::0:
fpr:::::::::{OTHER}:
uid:-::::1793702244::FB97F669B9117D5535C5E98A33BD15FEDF68C430::Other <o@example.invalid>:
"""
)

SECRET_KEY = """\
sec:u:2048:1:E16763323BBEEE75:1793702265:::u:::scSC:::+:::23::0:
fpr:::::::::4DE93B3B3F90D0F84DCEAE86E16763323BBEEE75:
grp:::::::::AB39AD1D15B2BA9C3FF09A6FF4EF74E3F3442008:
uid:u::::1793702265::8C92211FA263BEF2FAF9C60DA7D394460A7FE301::Test Signer <t@example.invalid>:
"""


@pytest.mark.parametrize(
    ("colons", "expected"),
    [
        pytest.param(ONE_KEY_WITH_SUBKEY, [PRIMARY], id="a primary key with a subkey lists the primary only"),
        pytest.param(TWO_KEYS, [PRIMARY, OTHER], id="a second key is listed after the first"),
        pytest.param(SECRET_KEY, [], id="a secret key is not a public key"),
        pytest.param("", [], id="no output"),
        pytest.param(f"fpr:::::::::{PRIMARY}:\n", [], id="an fpr record with no key before it"),
    ],
)
def test_lists_the_fingerprint_of_each_primary_public_key(colons, expected):
    assert gpg_primary_fingerprints(colons) == expected


def test_an_fpr_record_without_a_fingerprint_is_an_error():
    with pytest.raises(AnsibleFilterError, match="has no fingerprint"):
        gpg_primary_fingerprints("pub:-:2048:1:08958DCF2CE44379:1793702244:::-:::scESC::::::23::0:\nfpr:\n")


def test_input_that_is_not_text_is_an_error():
    with pytest.raises(AnsibleFilterError, match="expected gpg's text output"):
        gpg_primary_fingerprints(["pub:"])


def test_the_filter_is_registered_under_its_name():
    assert gpg_keys.FilterModule().filters() == {"gpg_primary_fingerprints": gpg_primary_fingerprints}
