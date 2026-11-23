# Running the Checks Without Docker or Registries

For any environment, whoever works in it, that has no Docker daemon or reaches GitHub but not container registries or Ansible Galaxy: a hosted sandbox, a laptop without Docker, or a host with filtered egress. It says which checks still run, which do not, and what stands in for them. CI is the authority either way; this is for getting a change right before it gets there.

## Pre-commit

- Neither `pre-commit` nor `shellcheck` needs installing: `uvx --python 3.14 pre-commit run --all-files`, and `uvx --from shellcheck-py shellcheck -x FILE`.
- The hooks that run a container image (the `-docker` ones) or reach the network (`gitleaks`, `zizmor`) cannot run. Skip them with `SKIP=<id>,<id>` and say which were skipped.
- The doc tools use Python 3.14 syntax, so the hooks fail when `pre-commit` runs on an older `python3`: pin it with `--python 3.14`, as above. Run a tool by itself with `uv run python -m doc_scripts.<tool>` from `tools/`, and run ruff and `uv run pytest` from there too.
- Run pre-commit twice: a hook that fixes a file fails the first time.
- Check a change in a clone with the whole history: `check-moved-files` reads it, and in a shallow clone (`--depth`) it says so and passes, so a mention of a removed file only shows up in a full one.

## Linters run by hand

- **`ansible-lint`** runs only at `pre-push`. Clone each needed collection from GitHub at its pinned version, then `ANSIBLE_COLLECTIONS_PATH=<dir> uv run --with ansible-lint ansible-lint --offline`. A module from a collection that cannot be cloned fails `syntax-check` on an untouched base as well; say so rather than working around it.
- **Compose files** lint with `npx -y dclint@<the version the hook pins> --config .config/.dclintrc FILE`. It cannot read a Jinja template, so lint the rendered output.
- **Mermaid** is rendered by [`check_mermaid`](../documentation/doc-checks.md#mermaid-render-check), which needs Docker. Without it, render with `mmdc` against a locally installed Chromium, using a Puppeteer config of `{"executablePath": "<chromium>", "args": ["--no-sandbox"]}`: `mmdc -p cfg.json -i d.mmd -o d.png -s 2`. Open the PNG, since a pass proves the block renders and not that it reads well.

## Verifying a series before delivery

Replay a `.series` file the way the maintainer will ([`landing-a-series.md`](landing-a-series.md)), on a fresh clone of `main`, with `--dry-run`, which pushes nothing and keeps no branch:

- `git clone --depth 50 https://github.com/wenenhoe/homelab.git`, then `pre-commit install` in it.
- Put a `pre-commit` shim on `PATH`: `printf '#!/bin/bash\nexec uvx --python 3.14 pre-commit "$@"\n' > ~/bin/pre-commit && chmod +x ~/bin/pre-commit`.
- Set `GIT_COMMITTER_NAME` and `GIT_COMMITTER_EMAIL`, and `SKIP` to the hooks that cannot run here (`gitleaks`, `zizmor` and the `-docker` ones, `ansible-lint`); say which were skipped.
- From `tools/` in a checkout of the tool: `uv run python -m land_series FILE.series --repo CLONE --base origin/main --no-fetch --dry-run`. It names whatever the machine lacks before it applies anything, replays each commit with the scope check and `pre-commit run --all-files`, and stops for a layer on its stop list. It runs no pre-push hook, which `--land` runs: check the push stage in a clone with the series applied, with `pre-commit run --hook-stage pre-push --from-ref origin/main --to-ref HEAD`, and `ansible-lint` skipped as above.

A layer that touches a path on the stop list prints `Read the patch, then type 'yes' to replay it:` and waits for a terminal. A session with no terminal answers it under a pseudo-terminal, once it has read the layer's patch, and starts the replay as a background command that writes to a log file, because a foreground command is cut off after 10 minutes. This driver answers that prompt and no other, and passes its arguments to `land_series`:

```python
import os
import pty
import sys

pid, fd = pty.fork()
if pid == 0:
    os.execvp("uv", ["uv", "run", "python", "-m", "land_series", *sys.argv[1:]])
tail = b""
while True:
    try:
        chunk = os.read(fd, 4096)
    except OSError:
        break
    sys.stdout.buffer.write(chunk)
    sys.stdout.flush()
    tail = (tail + chunk)[-200:]
    if tail.endswith(b"to replay it: "):
        os.write(fd, b"yes\n")
        tail = b""
sys.exit(os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))
```

A replay whose log has stopped growing while no `pre-commit`, `pytest` or `uv` process runs is waiting at that prompt and is not computing.

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
