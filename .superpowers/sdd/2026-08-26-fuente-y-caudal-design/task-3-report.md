# Task 3 report: Obsidian and Fuente Vault provisioning

## Status

G2 is **BLOCKED** for the real ready state. The physical temporary Vault and the
native empty setup screen were verified. The installed Obsidian CLI returned
code `1` because Obsidian was not running. Starting it or registering the
temporary Vault would write global Obsidian state and needs human consent.

## Official documentation checked

- Obsidian CLI: https://help.obsidian.md/cli
  - Requires the 1.12.7+ installer, explicit activation in Settings > General,
    and a running Obsidian app. Commands support the Vault in the current
    working directory. Used command: `obsidian vault info=path`.
  - The documented community-plugin commands are `plugins:restrict off` and
    `plugin:install id=<id>`; they run only for a non-empty approved allowlist.
- Storage: https://help.obsidian.md/data-storage
  - `.obsidian` is Vault-local; global settings are in the platform system
    folder. No global setting was changed.
- Community plugins: https://help.obsidian.md/community-plugins
  - Restricted Mode must be turned off before community-plugin installation;
    plugins run third-party code and are enabled only with explicit consent.

## Implementation and consent boundary

- Added `ObsidianProvisioner.inspect()` and `.provision()`.
- The target basename must be exactly `Fuente`; `consent=True` is mandatory.
- Provisioning creates the five pipeline roots, `.fuente`, `.obsidian`,
  `.fuente/state.db`, Vault-local `appearance.json`, and 14 atomically copied
  resources. It never creates or copies `workspace.json`.
- The packaged allowlist is deliberately empty: the SDD names no community
  plugin, so adding one would be unapproved third-party code. If plugins are
  added later, each has a pinned id/version and its installed `manifest.json`
  is checked; extra, missing, malformed, or version-mismatched manifests fail
  inspection.
- The native dialog confirms the exact path before sending `consent: true`.
  The fixed default filename is `Fuente` and the bridge rejects any omitted or
  false consent.
- `get_setup_status()` is read-only and reports the measured Vault inspection.

## Resource inventory

`Fuente/.fuente/templates/{reunion,tareas,objetivos,resumen,propiedades,contexto,concepto}/template.md`

`Fuente/.fuente/agents/{reunion,tareas,objetivos,resumen,propiedades,contexto,concepto}/AGENTS.md`

The temporary physical inventory contained exactly those 14 files, `state.db`,
`appearance.json`, all five stage directories, no visible template resource,
and no `.obsidian/workspace.json`.

## TDD and commands

- RED: `python3 -m pytest tests/test_obsidian_provisioner.py tests/test_setup_backend.py tests/test_installer_contract.py -q`
  failed collection with `ModuleNotFoundError: fuente.integrations.obsidian`.
- GREEN: focused provisioning, setup, installer, bridge, package-data, native
  evidence, and documentation checks passed: `65 passed in 1.55s`.
- Full suite was run once with `python3 -m pytest -q`; its only observed failure
  was the expected stale `docs/evidence/current-sdd.json` source digest before
  this task's evidence update.
- `git diff --check` passed before staging.
- `python3 scripts/verify_ui_evidence.py docs/evidence/fuente-y-caudal/manifest.json --head 08f5310466c0c9051f68dbd208d25d90c0c2b181`
  passed. The verifier now correctly preserves the historical G0 baseline while
  validating the later G2 capture at its own measured head.
- Real physical temporary run:
  `ObsidianProvisioner().provision(Path(temp_parent) / "Fuente", consent=True)`.
  It created the inventory above, returned `needs_obsidian_cli`, and recorded
  CLI available but not ready, `obsidian vault info=path` return code `1`.

## Native evidence and visual inspection

- `python3 -m fuente.main` opened a native PyWebView WebKit window titled
  `Fuente y Caudal`.
- `python3 scripts/capture_native_ui.py --title "Fuente y Caudal" --output docs/evidence/fuente-y-caudal/01-setup-empty.png --scenario setup-empty`
  captured `01-setup-empty.png`, owner `Python`, size `1280x802`, and WebKit
  runtime signal.
- Visual inspection confirmed the empty setup modal identifies Obsidian as
  available, offers `Crear Vault Fuente`, and describes selecting an existing
  Vault or creating the fixed Vault.
- `02-setup-ready.png` was not captured: the real transition requires the
  blocked CLI/app consent above. No synthetic screenshot was substituted.

## Files changed and review

- Provisioner, packaged resources, package metadata, setup API/backend, native
  bridge, initial-window title, setup UI copy, installer shared stage constant,
  focused tests, evidence manifest and this report.
- Self-review: no global Obsidian configuration write, no workspace state,
  no external dependency, no added community plugin, and no change to ETL,
  approval, quarantine, or sharing behavior.

## Commit and concern

Commit subject: `feat: provision the Fuente Obsidian vault`.

Concern: human consent is still required to start Obsidian, enable/register
its CLI if necessary, and complete the ready-state capture against the
temporary Vault.
