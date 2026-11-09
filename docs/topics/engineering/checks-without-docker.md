# Running the Checks Without Docker or Registries

For an environment with no Docker daemon, or one that reaches GitHub but not container registries or Ansible Galaxy: a hosted sandbox, or a host with filtered egress. It says which checks still run, which do not, and what stands in for them. CI is the authority either way; this is for getting a change right before it gets there.

## Pre-commit

- Neither `pre-commit` nor `shellcheck` needs installing: `uvx pre-commit run --all-files`, and `uvx --from shellcheck-py shellcheck -x FILE`.
- The hooks that run a container image (the `-docker` ones) or reach the network (`gitleaks`, `zizmor`) cannot run. Skip them with `SKIP=<id>,<id>` and say which were skipped.
- The doc tools use Python 3.14 syntax, so the hooks fail under an older system `python3`. Run them with `uv run python -m doc_scripts.<tool>` from `tools/`, and run ruff and `uv run pytest` from there too.
- Run pre-commit twice: `generate-doc-indexes` fails the first time it rewrites a view.
- A failed run can leave regenerated files unstaged; reset them before committing anything else, apart from the views in [`.githooks/generated-views`](../../../.githooks/generated-views) when a change is delivered as patches ([`pre-commit.md`](pre-commit.md#applying-patches-with-git-am)).

## Linters run by hand

- **`ansible-lint`** runs only at `pre-push`. Clone each needed collection from GitHub at its pinned version, then `ANSIBLE_COLLECTIONS_PATH=<dir> uv run --with ansible-lint ansible-lint --offline`. A module from a collection that cannot be cloned fails `syntax-check` on an untouched base as well; say so rather than working around it.
- **Compose files** lint with `npx -y dclint@<the version the hook pins> --config .config/.dclintrc FILE`. It cannot read a Jinja template, so lint the rendered output.
- **Mermaid** is rendered by [`check_mermaid`](ci/doc-checks.md#mermaid-render-check), which needs Docker. Without it, render with `mmdc` against a locally installed Chromium, using a Puppeteer config of `{"executablePath": "<chromium>", "args": ["--no-sandbox"]}`: `mmdc -p cfg.json -i d.mmd -o d.png -s 2`. Open the PNG, since a pass proves the block renders and not that it reads well.

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

## Git hooks

A change to [`.githooks/`](../../../.githooks) or to how patches are applied is tested with a real `git am` in a throwaway repository, as [`test_applypatch_hooks.py`](../../../tools/tests/doc_scripts/test_applypatch_hooks.py) does, with a control that fails without the hook.
