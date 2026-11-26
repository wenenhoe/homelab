# CI Image Tag Check

Weekly check that every image this repo pins still exists in its registry. How it fits the pipeline is in [CI: PR Checks](pipeline.md); the scheduled-job overview is in [`scheduled-jobs.md`](scheduled-jobs.md).

`check-image-tags.yml` runs [on a schedule](scheduled-jobs.md) and on demand. Renovate only ever proposes tags that exist, so a tag an upstream later
removes or renames goes unnoticed until a deploy fails to pull it;
[`tools/ci/images/remote.py`](../../../../tools/ci/images/remote.py) asks each
registry whether every image this repo pins is still there. Unlike
`check-pins`, it covers **every** image, not only the ones built here.

Nothing is listed by hand. It collects references from:

- `image:` lines in compose files and in Ansible YAML and templates: the
  `docker/` stacks, Molecule scenarios and fixtures, and task arguments;
- `FROM` and `COPY --from=<image>` in Dockerfiles, skipping build stages;
- every `customManagers` entry in `.github/renovate.json5` whose datasource is
  `docker`, applied to the files it names. These are the pins Renovate
  tracks outside compose: an rclone image in a systemd unit and a shell
  script, step-cli and step-ca in variable defaults and a CI script, the
  OpenBao image, the Renovate execution image, the images the Molecule
  playbooks run directly (`molecule_helpers/vars/images/*.yml`), and the
  mermaid-cli image the [diagram render check](../../documentation/doc-checks.md#mermaid-render-check)
  runs, a constant in `tools/doc_scripts/check_mermaid.py`. A manager that no longer
  matches any file, or a file that no longer matches its manager, fails the
  run: the pin moved, and this check would otherwise stop seeing it silently.

A reference pinned as `name:tag@sha256:...` is asked for by its digest, which
is what a host pulls. A registry that has deleted the digest fails the run
even while the tag still resolves, and the message says it is the digest that
is missing. The tag in a pinned reference is not requested.

Skipped, and listed in the output: a reference containing a template or
variable, `scratch`, and a `:local` tag (built on the host, never pushed;
today that is `buildapp:local`). A test fails if the skip list changes, so a
new one is a deliberate decision.

It uses the standard registry API with the standard library, so Docker
Hub, `ghcr.io` and any other v2 registry share one path: a HEAD request per
distinct image, and the anonymous token endpoint taken from the registry's
own 401 challenge. A HEAD request doesn't download the image.

Requests are built around registry rate limits:

| Behaviour | Detail |
| :--- | :--- |
| Pacing | One request at a time with a pause between; at most two HEADs per image, one token request per repository |
| 429 or 5xx | Retried, waiting for `Retry-After` (capped) or backing off, then one more pass after a cooldown |
| Never answered | A **warning** in the log and run summary, not a failure |
| 404, or 401/403 with a token | Fails the run: gone, renamed or private |

So an outage does not turn a run red and cannot hide a removed tag from the next one. The run needs no credentials and is read-only; GitHub emails a failure to whoever last changed the schedule.

The tests use a local server with the token flow, not a real registry. To list every reference and the files naming it, without a request:

```bash
cd tools && python3 -m ci.images.remote list
```

To run the live check now:

```bash
gh workflow run check-image-tags.yml
```

## Image inventory JSON

The same collection as one JSON document on stdout, again without a request:

```bash
cd tools && python3 -m ci.images.remote list --json
```

It exists
so a consumer outside this repo, the [image vulnerability
assessment](../../../decisions/0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md),
depends on a tested shape instead of the text output.

```json
{
  "version": 1,
  "images": [{ "ref": "redis:7", "digests": ["sha256:..."], "sources": ["docker/a/compose.yaml"] }],
  "skipped": [{ "ref": "buildapp:local", "reason": "built locally" }],
  "problems": []
}
```

- `images` has one entry per distinct reference, sorted by `ref`. `ref` is the
  reference without its digest, so an image keeps the same `ref` before and
  after it is pinned. `digests` lists the `sha256:` digests it is pinned to,
  sorted, and is empty while it is unpinned. `sources` holds the repo-relative
  files that name it, sorted.
- `skipped` is the list the text output prints, each with its reason.
- `problems` is non-empty when a Renovate manager lost its file or its text.
  The exit code is still 0, as for the text output, so a consumer treats a
  non-empty `problems` as an inventory it can't trust.
- When the inventory can't be built at all (an unreadable Renovate config),
  stdout stays empty, the error goes to stderr and the exit code is 1.
- `version` changes when a key is removed or changes meaning. Adding a key
  doesn't change it: `digests` was added without a bump, and `ref` kept its
  meaning.
