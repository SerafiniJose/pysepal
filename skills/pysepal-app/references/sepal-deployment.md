# SEPAL / Voila Deployment Reference

Hard-won rules from deploying a production pysepal Solara app (spatial_risk)
to SEPAL under voila. The unifying theme: **a whole class of failures is
invisible in local dev** and only appears on the deployed platform. Each
section names the failure mode and the guard.

## Environment spec (`sepal_environment.yml`)

- SEPAL rebuilds the module env from this file. It is the deploy authority;
  `pyproject.toml` mirrors it for dev tooling but the YAML wins on drift.
- **No `-e .`** in the pip block. Editable-installing the app pulls its
  pyproject pins into the conda env (a pinned `gdal==X` wheel silently
  shadows conda's GDAL and breaks the `_gdal_array` numpy bridge). The app
  runs in place under voila; nothing needs the install.
- **Pin every pip dep exactly.** Verified failure: an unpinned dep was
  renamed on PyPI; every SEPAL env built after the rename lacked the module
  the app imported, while local envs masked it via a stale git install.
- Compiled/geospatial deps (gdal, tippecanoe, ...) come from conda-forge;
  python version, gdal and numpy pinned to the tested dev env.
- If pysepal (or another dep) is consumed from a fork, install it in the pip
  block as `pkg @ git+https://github.com/<user>/<repo>.git@<branch>`.
- Verify the spec the way SEPAL will use it: throwaway
  `micromamba env create` from the file + a smoke test importing every
  runtime dep and the app packages.
- protobuf trap for incremental installs: deps capping `protobuf<7` can
  downgrade protobuf under a package that needs ≥7.x (grpcio-status). Fresh
  resolves are fine; incremental updates need explicit compatible pins.

## Voila entry (`ui.ipynb`)

- Keep it to three things: a `sys.path` shim, importing the app's `Page`,
  and displaying it. Business logic stays in the package.
- `kernelspec.name` must be SEPAL's module-venv name (`venv-<repo-name>`).
  Do not change it to `python3` — that breaks the deploy.
- **Voila does not fail loudly on a missing kernel.** It logs
  `WARNING | Could not find a kernel named '...', will use '<other>'` and
  runs the app in whatever kernel is registered — typically another module's
  env — producing import errors that look like a broken checkout. After any
  deploy, grep the log for `Could not find a kernel`.
- Register the kernel locally, inside the env so it travels with it:

      micromamba run -n <env> python -m ipykernel install \
        --prefix=<env-prefix> --name venv-<repo-name> \
        --display-name "(venv) <module>"

- Sessions under voila: pysepal `create_session` / `@with_sepal_sessions`
  are runtime-aware (since the voila-local-sessions work). Under
  solara-server they wait for auth headers; under voila (no HTTP layer, so
  `solara.lab.headers` is never populated) they build a real session from
  sandbox credentials (`/var/run/sepal-api-key` + `SEPAL_HOST`). If the app
  hangs at "Waiting for authentication headers...", the installed pysepal
  predates this — do not re-add header-seeding hacks to the notebook.
- A running voila serves the notebook it loaded at startup; restart it after
  editing `ui.ipynb` or app code.
- Launch that mirrors SEPAL (exercises import-time config, not shell exports):

      set -a; . ./.env; set +a
      voila ui.ipynb --port=8911 --no-browser --show_tracebacks=True

## Read-only CWD and scratch space

- SEPAL installs the module on a read-only mount and launches
  `voila ui.ipynb` with CWD = that mount, for the process lifetime.
  Consequences:
  - No relative output paths anywhere, including defaults deep inside
    third-party libs — pass absolute paths at every library boundary.
  - GDAL scratch files (`CPLGenerateTempFilename` falls back to `"."`)
    → `Read-only file system` at runtime. Set a writable scratch dir at
    **import time in Python** (both the env var and
    `gdal.SetConfigOption("CPL_TMPDIR", ...)`), with a real write-probe and
    a hard failure if no candidate is writable. Shell exports in run
    scripts never execute on SEPAL.
  - Add a regression test that chdirs into a read-only dir and runs the
    GDAL-heavy paths.
- Scratch sizing: proximity-type ops need ~4 bytes/px of scratch; large
  grids can exhaust a small tmpfs `/tmp` ("No space left on device") —
  make the scratch dir overridable.

## Binaries and PATH

- The SEPAL kernel's PATH may omit the conda env's `bin/`, so
  `shutil.which("tool")` misses binaries that ARE installed. Resolve
  external tools as: PATH lookup → sibling of `sys.executable`.
- Conda-installed binaries never appear in `pip list`; check
  `conda list <tool>` when auditing an env.

## Tile servers through the SEPAL proxy

- SEPAL exposes sandbox ports through jupyter-server-proxy and sets
  `LOCALTILESERVER_CLIENT_PREFIX` to a generic root-relative template
  (e.g. `/api/sandbox/jupyter/proxy/{port}`). Because the template is
  generic over `{port}`, it can carry *any* local tile server, not just
  localtileserver.
- For other tile servers (e.g. `vectortileserver` for PMTiles): at app
  startup, if `LOCALTILESERVER_CLIENT_PREFIX` contains `/proxy/{port}`,
  copy it into that server's prefix env var
  (`os.environ.setdefault("VECTORTILESERVER_CLIENT_PREFIX", prefix)`)
  **before the client object is constructed**. Range/206 requests survive
  jupyter-server-proxy, so PMTiles work through it.
- Do not rely on the jupyter-loopback comm bridge under Solara — the
  anywidget bridge does not mount via `solara.display()` (renders its repr,
  no JS half). Prefix-based proxying needs no bridge.
- Raw loopback URLs (`http://127.0.0.1:<port>/...`) work in local dev by
  direct same-machine fetch, silently masking a broken proxy/bridge — test
  reachability through a fake `/proxy/{port}` reverse proxy locally before
  believing it.

## Local testing side effects

- Running the app rewrites `~/.sepal-ui-config` (e.g. `theme = dark`);
  theme-dependent tests then fail for a full suite run right after a manual
  UI session. Pin the config (conftest) or restore it before trusting
  failures.
- Never `pip install --force-reinstall` a dep while a test suite is running
  in the same env — the ripped dist-info fakes unrelated failures.

## Deploy verification checklist

- [ ] Throwaway env build from `sepal_environment.yml` + import smoke test
- [ ] No `-e .`; every pip dep pinned; forks pinned to branch/tag
- [ ] `ui.ipynb` kernelspec = `venv-<repo-name>`; local kernel registered
- [ ] App boots under bare `voila ui.ipynb` (no shell env exports)
- [ ] GDAL scratch + outputs verified with a read-only CWD test
- [ ] External binaries resolve without PATH (sys.executable-sibling probe)
- [ ] Tile layers verified through a simulated `/proxy/{port}` prefix
- [ ] SEPAL log grepped for `Could not find a kernel` after deploy
