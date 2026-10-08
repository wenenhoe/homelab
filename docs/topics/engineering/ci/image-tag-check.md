# CI Image Tag Check

Weekly check that every image this repo pins still exists in its registry. How it fits the pipeline is in [CI: PR Checks](pipeline.md); the scheduled-job overview is in [`scheduled-jobs.md`](scheduled-jobs.md).

`check-image-tags.yml` runs once a week and on demand.
Renovate only ever proposes tags that exist, so a tag an upstream later
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
  mermaid-cli image the [diagram render check](doc-checks.md#mermaid-render-check)
  runs, a constant in `tools/doc_scripts/check_mermaid.py`. A manager that no longer
  matches any file, or a file that no longer matches its manager, fails the
  run: the pin moved, and this check would otherwise stop seeing it silently.

Skipped, and listed in the output: a reference containing a template or
variable, `scratch`, and a `:local` tag (built on the host, never pushed;
today that is `buildapp:local`). A test fails if the skip list changes, so a
new one is a deliberate decision.

It uses the standard registry API with the standard library, so Docker
Hub, `ghcr.io` and any other v2 registry share one path: a HEAD request per
distinct image, and the anonymous token endpoint taken from the registry's
own 401 challenge. A HEAD request doesn't download the image.

**Rate limiting** is the risk this is built around:

- one request at a time, with a half-second pause between requests. Each
  image costs at most two HEADs plus, once per repository, a token request:
  the images across the two registries (`ghcr.io` and Docker Hub) come to a
  few requests each, once a week;
- a token cached per repository, and reused across its tags;
- a 429 or 5xx is retried up to five times, waiting as long as `Retry-After`
  says (capped at a minute) or backing off 2, 4, 8, 16 seconds;
- whatever is still unanswered gets one more pass after a minute's cooldown;
- an image whose registry never answered is a **warning**, not a failure: it
  shows in the log and the run summary as not checked this run. Only a tag
  the registry says isn't there (a 404, or a 401/403 even with a token: gone,
  renamed or private) fails the run. A registry outage doesn't turn a weekly
  run red, and it can't hide a removed tag from the next week's.

The check sends HEAD requests for manifests. A registry rate limit would meet
the retry and warning paths above. The run needs no credentials and runs with
read-only permissions. GitHub emails the
workflow's failure to the person who last changed the schedule.

The tests speak real HTTP to a local server that implements the token flow
and can answer 429 and 5xx; **they don't reach a real registry**, so the
first `workflow_dispatch` run against `ghcr.io` and Docker Hub is the live
check. `python -m ci.images.remote list` (from `tools/`) prints every
reference and the files naming it without making a request.

## Image inventory JSON

`python -m ci.images.remote list --json` (from `tools/`) prints the same
collection as one JSON document on stdout, again without a request. It exists
so a consumer outside this repo, the [image vulnerability
assessment](../../../decisions/0071-assessing-the-vulnerabilities-of-deployed-container-images/revision-000.md),
depends on a tested shape instead of the text output.

```json
{
  "version": 1,
  "images": [{ "ref": "redis:7", "sources": ["docker/a/compose.yaml"] }],
  "skipped": [{ "ref": "buildapp:local", "reason": "built locally" }],
  "problems": []
}
```

- `images` has one entry per distinct reference, sorted by `ref`. `sources`
  holds the repo-relative files that name it, sorted.
- `skipped` is the list the text output prints, each with its reason.
- `problems` is non-empty when a Renovate manager lost its file or its text.
  The exit code is still 0, as for the text output, so a consumer treats a
  non-empty `problems` as an inventory it can't trust.
- When the inventory can't be built at all (an unreadable Renovate config),
  stdout stays empty, the error goes to stderr and the exit code is 1.
- `version` changes when a key is removed or changes meaning. Adding a key
  doesn't change it.
