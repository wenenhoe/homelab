# Apt signing keys

The keys that sign the third-party apt repositories this repo installs from:
Docker's, by the `docker` role, and Tailscale's, by the `tailscale_node` role.
apt trusts every key in the file a repository's `signed_by` names, so a key
that is fetched and trusted unchecked makes the vendor's host the whole trust
root. Each role pins the key's fingerprint and installs the key only if what
it downloaded is exactly that key.

## What a run does

1. Download the key to a staging file next to its final path
   (`docker.asc.fetched`, `tailscale.gpg.fetched` in `/etc/apt/keyrings`).
   This runs in a check run too, because it writes only the staging file and
   the next steps read it.
2. List the primary keys in the staging file with `gpg --show-keys`, using a
   throwaway home directory: `gpg` stops when its home is missing, and one it
   creates in root's would stay behind.
3. Stop unless that list is exactly the pinned fingerprint. A second key in the
   file fails it as a different key does, because apt would trust both. The
   comparison is [`gpg_primary_fingerprints`](../../../ansible/filter_plugins/gpg_keys.py)
   against a one-item list.
4. Copy the staging file to the path apt reads.

A failure at step 3 leaves the installed key as it was. The key is checked on
every run, so a vendor that rotates its key stops the next run that reaches
the role instead of being trusted.

## Where the pins are

| Key | Pin | Also |
| :--- | :--- | :--- |
| Docker | `docker_apt_key_fingerprint` in [`roles/docker/defaults/main.yaml`](../../../ansible/roles/docker/defaults/main.yaml) | The same fingerprint in [`docker/molecule-dind/Dockerfile`](../../../docker/molecule-dind/Dockerfile), which installs the key at image build time. A test fails when the two differ. |
| Tailscale | `tailscale_node_apt_key_fingerprint` in [`roles/tailscale_node/defaults/main.yaml`](../../../ansible/roles/tailscale_node/defaults/main.yaml) | |

Docker states its fingerprint on its install page for Ubuntu. Tailscale's
install pages give the key's download address and no fingerprint; its pin is
the key the repository's packages are signed with, whose id `apt` reports in a
`NO_PUBKEY` error as the last sixteen characters of the same value.

## When a vendor rotates its key

The run fails with the fingerprints the download holds and the one pinned. Do
not change the pin to what the download holds. Get the new fingerprint from a
second channel, such as the vendor's documentation, the key on a host that
still has it (`gpg --show-keys /etc/apt/keyrings/<key file>`), or the
`NO_PUBKEY` id apt reports, then change the pin, and the Dockerfile's copy for
Docker, in one change.

## What is not covered

Nothing asks the vendors on a schedule, so a rotation shows at the next run of
the role, not before it. The Molecule scenarios of both roles download the real
keys, so a pin that is wrong fails there first.
