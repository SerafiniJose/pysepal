# Pysepal App Defaults

These defaults were recovered from the saved pysepal design session and should be treated as the current baseline unless the user explicitly overrides them.

## Agreed Defaults

- Ask the user to choose the app type explicitly.
- New apps always use `solara.reactive()` AppState.
- New apps never scaffold traitlets observer flows as the primary pattern.
- Always include `component/message/` and the Translator pattern.
- Use live pysepal source discovery instead of a baked-in component list.
- `sepal_environment.yml` is the deploy authority for dependencies; `pyproject.toml` mirrors it for dev tooling (see Dependency Defaults below).
- Do not create `requirements.txt`.
- Create `sepal_environment.yml`.
- Skip `noxfile.py` by default.
- Use a two-pass scaffold:
  - base runnable scaffold
  - notebook/repo-specific enrichment

## Standard Project Structure

```text
project/
├── pyproject.toml
├── sepal_environment.yml
├── .pre-commit-config.yaml
├── component/
│   ├── model/
│   ├── tile/
│   ├── widget/
│   ├── scripts/
│   ├── parameter/
│   └── message/
└── ...
```

## GEE / Container App Files

Default output set:

- `solara_app.py`
- `run_solara.sh`
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.override.yml` when local overrides are useful
- `supervisord.conf`
- env bootstrap files as needed
- the standard `component/` tree

Auth expectations:

- work with SEPAL header/env auth when available
- work with local `earthengine authenticate` credentials when developing outside SEPAL

GEE execution expectations:

- follow `docs/guides/solara-gee-patterns.md`
- use `solara.lab.use_task`
- use immutable request snapshots
- keep task state mirrored into AppState

User file expectations:

- use `get_current_sepal_client()` / `SepalClient` for all user-file reads,
  writes, directory creation, and listing
- never write user data to the container filesystem
- do not scaffold `Path`, `os`, `shutil`, `glob`, `open()`, or similar
  filesystem access for user workspace data in GEE/container apps
- keep the same `SepalClient` code path in local development and SEPAL
  deployment; do not branch to local filesystem writes

## Local / Voila App Files

Default output set:

- `pyproject.toml`
- `sepal_environment.yml`
- notebook or Voila entrypoint files
- the standard `component/` tree

Local apps still use:

- pysepal Solara components
- `solara.reactive()` AppState
- pyproject-managed Python dependencies
- pre-commit tooling
- Translator/i18n structure

User file expectations:

- resolve the output root once in `component/parameter/directory.py` as
  `Path.home() / "module_results" / "<module_name>"`; create it with
  `mkdir(parents=True, exist_ok=True)`
- every save/load/list path in the app goes through that single constant
- never scaffold repo-relative output folders (`data/`, `results/`, `output/`)
- an env-var override of the default root is acceptable for dev/tests

## Dependency Defaults

`sepal_environment.yml` is the deploy authority — it is what SEPAL installs
when building the module env. `pyproject.toml` mirrors its Python deps for dev
tooling (and holds tool config), but the conda YAML wins on any drift.

Do **not** install the local project from the YAML (no `-e .`): the app runs
in place under voila, and pyproject pins pulled in by an editable install can
poison the conda geospatial stack (see `references/sepal-deployment.md`).
Pin every pip dep in the YAML exactly:

```yaml
dependencies:
  - pip
  - pip:
      - somedep==1.2.3
      # no -e .
```

## Repo-Local Draft Target

The first draft of the skill should live in:

- `skills/pysepal-app/SKILL.md`
- `skills/pysepal-app/agents/openai.yaml`

Install or copy it into a user-specific skill directory only after the repo-local version is reviewed.
