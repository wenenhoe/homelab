# Backup & Restore Data Flow

The one end-to-end view that spans three separate topic docs —
[`disaster-recovery.md`](../disaster-recovery.md) (the backup side),
[`cloud-sync.md`](../cloud-sync.md) (the offsite relay), and
[`restore.md`](../restore.md) (reversing the path) — none of which
shows the whole pipeline on one page.

## Backup: app host to offsite cloud

```mermaid
flowchart LR
    vol[("App's named volume<br/>on its own host")]
    agent["backup_agent<br/>(docker-volume-backup)"]
    gpg1{{"GPG encrypt"}}
    seaweed[("SeaweedFS<br/>on storage,<br/>path-scoped per host")]
    sync["cloud_sync<br/>(storage only)"]
    r2[("Cloudflare R2")]
    b2[("Backblaze B2")]
    oci[("OCI Object Storage")]

    vol --> agent --> gpg1 -- "nightly, per-app schedule" --> seaweed
    seaweed -- "read already-encrypted objects,<br/>relay onward — never decrypts" --> sync
    sync --> r2 & b2 & oci
```

Every app host's `backup_agent` identity can write only its own
`homelab-backups/<hostname>-*` prefix; only `storage` ever holds a
cloud write credential. See
[`disaster-recovery.md`](../disaster-recovery.md#threat-model) for why.

## Restore: cloud/SeaweedFS back to an app host's volume

```mermaid
flowchart LR
    r2[("Cloudflare R2")]
    b2[("Backblaze B2")]
    oci[("OCI Object Storage")]
    seaweed[("SeaweedFS")]
    ctl["restore_all.py<br/>(controller, read-only leaf creds)"]
    gpg2{{"GPG decrypt"}}
    ansible["playbooks/restore.yaml<br/>(ansible-playbook)"]
    vol[("Target app's<br/>named volume")]

    seaweed -- "1st: discover latest archive" --> ctl
    r2 & b2 & oci -. "fallback only, if<br/>SeaweedFS unreachable" .-> ctl
    ctl --> gpg2 --> ansible -- "stop app, extract archive,<br/>redeploy" --> vol
```

The controller never holds a write credential for SeaweedFS or any
cloud target — only the six read-leaf credentials from
[`cloud-credential-creation.md`](../cloud-credential-creation.md), and
only for the discovery/fallback step above. The actual extraction runs
through the same `restore` Ansible role either way, on the target app
host itself.
