"""The permission groups Cloudflare's token API offers an R2 token, as `r2_permission_group_ids` returns them.

Both are present, so a test that stubs the lookup can tell a token minted with the right group from one
minted with the other, which a stub holding only the expected group could not.
"""

from __future__ import annotations

R2_GROUPS = {
    "Workers R2 Storage Bucket Item Write": "grp-write",
    "Workers R2 Storage Bucket Item Read": "grp-read",
}
