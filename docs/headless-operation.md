# Headless operation (Docker, NAS and CI)

Fuente can run as a **continuous background worker** without Tkinter or PyWebView.
Use this mode on servers, NAS appliances, and CI runners where no graphical
display is available.

## Entry points

| Command | Use case |
|---------|----------|
| `fuente --headless --vault /path/to/vault` | Continuous ingestion + graph refinement (Docker default) |
| `fuente --flush --vault /path/to/vault` | One-shot deterministic pass; no background threads |
| `fuente --vault /path/to/vault` | Desktop GUI (requires a display) |

The Docker image sets `CMD ["--headless", "--vault", "/vault"]` so containers
start the worker automatically.

## Vault layout and volumes

Mount your Obsidian Vault at `/vault` (or any path passed to `--vault`). Fuente
expects the standard four-stage tree:

- `1_entrada/` — drop files here for ingestion
- `2_sucio/` — original copies for audit
- `3_limpio/` — verbatim Markdown transcriptions
- `4_salida/` — atomic notes with `[[WikiLinks]]`
- `.fuente/` — system state (see below)

In `docker-compose.yml` the bind mount is `./ObsidianVault:/vault`. Persist
this directory on the host so notes and state survive container restarts.

## State database (`.fuente/state.db`)

ETL job progress is stored in `<vault>/.fuente/state.db` (SQLite). The headless
worker resumes interrupted jobs on startup via `ApplicationLifecycle` and
`FolderMonitor`. Keep `.fuente/` on the same volume as the Vault; deleting it
forces a full re-ingest of pending files.

Other `.fuente/` contents:

- `config.json` — persisted settings (overridden at runtime by env vars below)
- `chroma/` — local vector index for RAG
- `quarantine/` — files that failed processing

## Ollama configuration

Docker Compose sets:

```yaml
environment:
  - OLLAMA_URL=http://ollama:11434
  - ALLOW_NON_LOOPBACK_OLLAMA=true
```

`OLLAMA_URL` is applied **only after validation** (`validate_ollama_url` in
`fuente/config.py`). Non-loopback URLs (e.g. the `ollama` service hostname)
require `ALLOW_NON_LOOPBACK_OLLAMA=true`. Invalid values are logged and
ignored so the process does not silently use `localhost` inside the container.

### First run: pull models manually

The Compose stack starts an empty Ollama service. Fuente can connect to Ollama
immediately, but **LLM inference will not work until at least one model is
pulled**. After `docker compose up -d`, pull a model into the Ollama container
(for example `qwen2.5:7b`, which matches the RAM Governor defaults on many
hosts):

```bash
docker exec -it fuente_ollama_service ollama pull qwen2.5:7b
```

Repeat for any other model you configure via `custom_model_override` in
`.fuente/config.json`. Model weights persist in the `ollama_storage` volume.

## Shutdown

Headless mode registers handlers for **SIGINT** (`Ctrl+C`) and **SIGTERM**
(`docker stop`). Either signal ends the wait loop, then the `run_headless`
`finally` block calls `ApplicationLifecycle.stop()`, which:

1. Stops `FolderMonitor` (bounded join on the poll thread)
2. Stops `OptimizadoGraphLoop` (bounded join on the graph thread)
3. Closes the ETL pipeline and its SQLite job-store connection

Allow a few seconds for graceful shutdown; the default Docker stop timeout
(10 s) is usually sufficient.

## GUI vs headless

| | GUI (`fuente --vault …`) | Headless (`fuente --headless …`) |
|--|-------------------------|----------------------------------|
| Tkinter / PyWebView | Yes | Never imported |
| Background services | Yes (`ApplicationLifecycle` continuous) | Same (`mode="headless"`) |
| Display required | Yes (Linux: `DISPLAY` or `WAYLAND_DISPLAY`) | No |

If you launch the default GUI command without a display, Fuente exits immediately
with a message pointing to `--headless` or `--flush`.
