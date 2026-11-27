# Running the Checks Without Docker or Registries

For any environment, whoever works in it, that has no Docker daemon or reaches GitHub but not container registries or Ansible Galaxy: a hosted sandbox, a laptop without Docker, or a host with filtered egress. It says which checks still run, which do not, and what stands in for them. CI is the authority either way; this is for getting a change right before it gets there. A Claude Code cloud session has Docker and registry access once prepared; see [`hosted-sessions.md`](hosted-sessions.md).

## What runs here

| Check | Without Docker or registries | Instead |
| :--- | :--- | :--- |
| Most pre-commit hooks, unit tests | runs | nothing needed |
| The `-docker` hooks | skipped | `uvx` or `npx` forms below |
| `gitleaks`, `zizmor` (network) | skipped | CI |
| `ansible-lint` | needs collections | clones from GitHub |
| Mermaid render | needs Docker | `mmdc` on a local Chromium |
| A pinned image | cannot be pulled | [build it from its release](#docker-without-registries) |

## Pre-commit

Neither `pre-commit` nor `shellcheck` needs installing:

```bash
uvx --python 3.14 pre-commit run --all-files
```

```bash
read -r -p 'shell script: ' file && uvx --from shellcheck-py shellcheck -x "$file"
```

- Skip hooks that cannot run with `SKIP=<id>,<id>`, and say which were skipped.
- The doc tools use Python 3.14 syntax, so an older `python3` fails the hooks: keep `--python 3.14`. Run one tool by itself as `uv run python -m doc_scripts.<tool>` from `tools/`, and ruff and `uv run pytest` from there too.
- Run pre-commit twice: a hook that fixes a file fails the first time.
- Use a clone with the whole history: in a shallow one `check-moved-files` says so and passes.

## Linters run by hand

**`ansible-lint`** runs only at `pre-push`. Clone each needed collection from GitHub at its pinned version into one directory, then:

```bash
read -r -p 'collections directory: ' dir && ANSIBLE_COLLECTIONS_PATH="$dir" uv run --with ansible-lint ansible-lint --offline
```

A module from a collection that cannot be cloned fails `syntax-check` on an untouched base too; say so rather than working around it.

**Compose files** lint with the `dclint` version the hook pins. It cannot read a Jinja template, so lint the rendered output:

```bash
read -r -p 'dclint version the hook pins: ' version; read -r -p 'compose file: ' file
```

```bash
npx -y "dclint@$version" --config .config/.dclintrc "$file"
```

**Mermaid** is rendered by [`check_mermaid`](../documentation/doc-checks.md#mermaid-render-check), which needs Docker. Without it, use `mmdc` with a local Chromium, and open the PNG, since a pass proves the block renders and not that it reads well:

```bash
read -r -p 'chromium path: ' chromium; read -r -p 'diagram file (.mmd): ' diagram
```

```bash
printf '{"executablePath": "%s", "args": ["--no-sandbox"]}\n' "$chromium" > /tmp/puppeteer.json
mmdc -p /tmp/puppeteer.json -i "$diagram" -o /tmp/diagram.png -s 2
```

## Verifying a series before delivery

Replay a `.series` file the way the maintainer will ([`landing-a-series.md`](landing-a-series.md)), on a fresh clone of `main`, with `--dry-run`, which pushes nothing and keeps no branch:

From a checkout of the tool:

```bash
clone=$(mktemp -d)
git clone --depth 50 https://github.com/wenenhoe/homelab.git "$clone"
(cd "$clone" && uvx --python 3.14 pre-commit install)
mkdir -p ~/bin
printf '#!/bin/bash\nexec uvx --python 3.14 pre-commit "$@"\n' > ~/bin/pre-commit && chmod +x ~/bin/pre-commit
```

Set `GIT_COMMITTER_NAME` and `GIT_COMMITTER_EMAIL`, put `~/bin` on `PATH`, and set `SKIP` to the hooks that cannot run here, saying which. Then:

```bash
# paste alone; it waits for the series file's path, absolute or from tools/
read -r -p 'series file: ' series
```

A replay can run longer than the 10 minutes a foreground command is given, so it runs in the background and writes to a log file that ends with its exit status:

```bash
cd tools
log=$(mktemp)
(uv run python -m land_series "$series" --repo "$clone" --base origin/main --no-fetch --dry-run --accept-stops; echo "exit $?") > "$log" 2>&1 &
replay=$!
```

Then wait for the process rather than for a length of time. This returns as soon as the replay ends, or after 590 seconds, in which case run it again:

```bash
timeout 590 tail --pid="$replay" -f "$log"
```

It names whatever the machine lacks before it applies anything, replays each commit with the scope check and `pre-commit run --all-files`, and lists the commits on [the stop list](landing-a-series.md#the-stop-list), which `--accept-stops` replays without asking. Pass it only after reading those commits' patches, and only on a throwaway machine. It runs no pre-push hook, which `--land` runs: check the push stage in a clone with the series applied, with `ansible-lint` skipped as above:

```bash
pre-commit run --hook-stage pre-push --from-ref origin/main --to-ref HEAD
```

A change to how `git am` is used is tested with a real `git am` in a throwaway repository.

## Docker without registries

A pinned image cannot be pulled, so test the software it packages: build it or download it from its GitHub tag or release at the pinned version, check any download against the repo's pin, and run it in a rootfs imported into a private daemon.

- Run `dockerd` with `--storage-driver vfs --iptables=false --bridge=none` and its own `--host` socket, `--data-root`, `--exec-root` and `--pidfile`. Keep every one of those paths short: a unix socket path is limited to 108 bytes.
- Import the rootfs as the test image: a shell, the tools the test uses, the binary under test and every library they load, including ones loaded at run time (`libgcc_s.so.1`), which `ldd` does not list.
- Use `network_mode: none` and `docker build --network none`. Where the software binds IPv4 and IPv6 and the network has no IPv6, turn its IPv6 off.
- Stop the daemon through its pid file; `pkill -f` can match its own shell.
- A restart path is checked with `docker create` once and `docker start -a` twice.
- When a capability or permission is under test, add a control that fails without it, so the harness is shown able to catch the failure.

This proves behaviour on the host's kernel, with GNU coreutils in place of BusyBox. For `no-new-privileges` and file capabilities, the real hosts are the authority.

A test target for an external service is a local process or container on a user-defined network (`rclone serve s3` for S3). A target that caches listings or state gets its own path for each test variant. Read a container's address from `NetworkSettings.Networks`, since the top-level `NetworkSettings.IPAddress` can be empty.
