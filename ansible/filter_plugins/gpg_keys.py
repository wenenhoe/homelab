"""gpg_primary_fingerprints: the primary-key fingerprints in `gpg --show-keys --with-colons` output.

apt trusts every key in a file named by `Signed-By`, so a download is checked
by what it holds in total: a file with the pinned key plus a second one would
verify the pinned fingerprint and still let the second key sign packages. The
roles that fetch a vendor's apt key compare this list to a one-item list.

    {{ gpg_output.stdout | gpg_primary_fingerprints }}  ->  ["9DC858229FC7..."]

A subkey's fingerprint is not in the list: gpg prints one `fpr` record for
each key, and only the one that follows a `pub` record belongs to a primary
key. A secret key (`sec`) is not a public key and contributes nothing, so a
file that holds only that fails the comparison.
"""

from __future__ import annotations

from ansible.errors import AnsibleFilterError

# gpg's colon format puts the fingerprint in the tenth field of an `fpr` record.
_FINGERPRINT_FIELD = 9


def gpg_primary_fingerprints(colons: str) -> list[str]:
    """The fingerprint of each primary public key, in file order."""
    if not isinstance(colons, str):
        raise AnsibleFilterError(f"gpg_primary_fingerprints: expected gpg's text output, got {type(colons).__name__}")
    fingerprints = []
    after_primary = False
    for line in colons.splitlines():
        record = line.split(":")
        if record[0] == "pub":
            after_primary = True
        elif record[0] == "fpr" and after_primary:
            if len(record) <= _FINGERPRINT_FIELD or not record[_FINGERPRINT_FIELD]:
                raise AnsibleFilterError(f"gpg_primary_fingerprints: an fpr record has no fingerprint: {line}")
            fingerprints.append(record[_FINGERPRINT_FIELD])
            after_primary = False
        elif record[0] in {"sub", "sec", "ssb"}:
            after_primary = False
    return fingerprints


class FilterModule:
    def filters(self):
        return {"gpg_primary_fingerprints": gpg_primary_fingerprints}
