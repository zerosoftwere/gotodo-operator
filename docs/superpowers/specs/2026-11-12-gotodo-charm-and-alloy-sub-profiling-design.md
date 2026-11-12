# GoTodo charm, observed through alloy-sub: design

Date: 2026-11-12
Status: draft, awaiting approval

## Intent

Run the GoTodo app (`ibrahim-dwellir/gotodo`, a single static Go binary) as a Juju machine
charm.

- **Metrics and logs:** gotodo publishes its Prometheus metrics endpoint and its systemd
  unit over `machine-observability` to Dwellir's `alloy-sub` subordinate
  (`/home/ibrahim/Projects/alloy-sub-operator`). `alloy-sub` remote-writes the metrics and
  ships the journal to Loki.
- **Dashboards:** gotodo ships its two Grafana dashboards over a direct `grafana-dashboard`
  relation (interface `grafana_dashboard`) to `grafana-vm` or `grafana-k8s`. This is the
  pattern `dwellir-observability-reference` uses; its README says "Alloy is not involved
  in dashboard delivery".
- **Profiles:** gotodo's Go pprof profiles go to Dwellir's `pyroscope-vm` charm
  (`/home/ibrahim/Projects/pyroscope-vm-operator`), also through `alloy-sub`. They use a
  separate `profiling-source` endpoint (interface `pprof_scrape`), because that is the only
  profiling contract `iris-operator` supports. `alloy-sub` gains profiling support for this.

**`opentelemetry-collector` and `cos-agent` are not used.** The user decided this: one Alloy
agent per machine handles metrics, logs and profiles.

**The relations are independent.** `alloy-sub` always needs `juju-info`: it waits with
"config waiting for juju-info relation" without it and takes its topology from it. On top of
that, an operator can relate `machine-observability`, `profiling-source`, or both. Iris
relates only `profiling-source` (plus its own `metrics-endpoint`).

Why profiles don't go through Canonical's `opentelemetry-collector` (kept here for the record):

- **The collector charm can't pull pprof.** Its `receive-profiles` endpoint (interface
  `profiling`) only accepts profiles pushed over OTLP, and `cos_agent` has no profiling
  fields.
- **Its OTLP profiles are the wrong layout anyway.** The `pyroscope-vm` validation
  (`pyroscope-vm-operator/docs/validation.md`) shows the collector charm's otelcol v0.130.0
  sends an older layout. Pyroscope 1.21.0 rejected it with HTTP 400 `wrong wireType`.
- **eBPF gives CPU only.** Canonical's machine profiling route, the `otel-ebpf-profiler`
  charm, has no memory, mutex, block or goroutine profiles.

Why `alloy-sub` is the right place:

- **Alloy speaks pprof natively.** `pyroscope.scrape` pulls Go pprof and `pyroscope.write`
  pushes Pyroscope's native format. There is no alpha OTLP Profiles format to keep in step,
  and `pyroscope-vm`'s validation already proved native pprof ingestion.
- **It is already on Dwellir machines.** `alloy-sub` installs Alloy and runs it under
  systemd. With metrics, logs and profiles all there, each machine runs one agent.
- **Iris already speaks this contract.** `iris-operator` already publishes its pprof target
  on `profiling-source` (interface `pprof_scrape`), and its `profile_types` use Alloy's
  `pyroscope.scrape` block names word for word. `alloy-sub` consumes that endpoint, so Iris
  works unchanged as well as gotodo.

## The two deliverables, in build order

1. **`gotodo-operator`**, this repo (`/home/ibrahim/tut/spike/pyroscope/gotodo-operator`).
   It works with today's `alloy-sub` for metrics and logs, and with Grafana for dashboards,
   before any profiling work lands.
2. **Profiling in `alloy-sub-operator`** (`/home/ibrahim/Projects/alloy-sub-operator`,
   remote `dwellir-public/alloy-sub-operator`). A feature branch from `main` and a PR. That
   repo has unrelated, untracked work in `docs/superpowers/{specs,plans}/2026-08-27-*`.
   Don't touch, commit or delete it.

The `pprof_scrape` payload (below) is the contract between them. `alloy-sub` owns the
library and gotodo vendors it. Build order: write the library in `alloy-sub` first, which is
small and has no dependencies, then gotodo's provider, then `alloy-sub`'s consumer.

**Step 0** (Part 2) is a short throwaway spike that runs before either charm's profiling
code.

Target topology:

```
juju deploy ./gotodo-operator_*.charm gotodo
juju deploy ./alloy-sub_*.charm alloy-sub          # or the existing alloy-sub application

juju relate alloy-sub:juju-info gotodo                                    # always: attach + topology
juju relate gotodo:machine-observability alloy-sub:machine-observability  # metrics + journal logs
juju relate gotodo:profiling-source alloy-sub:profiling-source            # profiles
juju relate alloy-sub:send-remote-write <mimir/prometheus>
juju relate alloy-sub:send-loki-logs <loki>
juju relate alloy-sub:send-profiles pyroscope-vm:profiling
juju relate gotodo:grafana-dashboard grafana-vm:grafana-dashboard         # or grafana-k8s
juju relate pyroscope-vm:grafana-source grafana-vm                        # Pyroscope datasource
```

If a backend or Grafana lives in another model, offer and consume it across models. All the
backend-facing relations (`send-*`, `profiling`, `grafana-dashboard`) are global scope.
`dwellir-observability-reference`'s README shows the `grafana-dashboard` offer/consume
commands.

```
 gotodo machine ──────────────────────────────────────────────────────────────
 gotodo.service                       alloy (alloy-sub subordinate)
 :8080 public UI/API/health
 127.0.0.1:6060/metrics ◀──────────── prometheus.scrape ── remote_write ──▶ Mimir/Prometheus
 journal (gotodo.service) ◀────────── loki.source.journal ── loki.write ──▶ Loki
 127.0.0.1:6060/debug/pprof/* ◀────── pyroscope.scrape ── pyroscope.write ──▶ pyroscope-vm :4040

 gotodo charm ── grafana-dashboard ───────────────────────────────────────────▶ grafana-vm / grafana-k8s
```

## Goals

- Install, run and upgrade gotodo from GitHub releases on Ubuntu 24.04, amd64 only.
- Run gotodo as a dedicated `gotodo` system user under systemd.
- Provide `start`, `stop` and `restart` actions.
- Metrics and journal logs reach the backends through `alloy-sub` over `machine-observability`.
- Both dashboards reach Grafana over a direct `grafana-dashboard` relation.
- CPU, memory (delta), mutex (delta), block (delta) and goroutine profiles reach
  `pyroscope-vm`, labelled with `service_name` and Juju topology.
- `alloy-sub` profiles any principal that publishes `pprof_scrape`, starting with gotodo
  and Iris, on both bases `alloy-sub` already builds for (22.04 and 24.04, amd64).

## Non-goals

- arm64 or other architectures (the release has arm64, but the user asked for amd64 only).
- Shared state across gotodo units. Each unit has its own SQLite database; there is no
  clustering, load balancer or ingress integration.
- `opentelemetry-collector` and `cos-agent`.
- Alert rules (`machine-observability` v3 artifacts). The payload is v3, so rules can be
  added later without a schema change.
- Traces.
- Changing the gotodo Go app.
- Changing `iris-operator`, `pyroscope-vm-operator` or `opentelemetry-collector-operator`.
- Profiles over OTLP, or carried inside `machine-observability`. There is one profiling
  contract, `pprof_scrape`, shared with Iris.

## Anti-goals (failure even if it "works")

- The pprof or metrics port reachable from off the machine. pprof has no authentication.
- The JWT secret or other credentials in logs, action output or world-readable files.
- A downloaded binary used without its checksum being verified.
- Breaking the existing Iris `profiling_source` payload, or requiring Iris to change to be
  consumed.
- Profiles in Pyroscope as ever-growing cumulative totals (heap alloc, mutex, block). gotodo
  avoids this with godeltaprof endpoints. For Iris's plain endpoints, see Step 0.
- Regressing existing `alloy-sub` metrics, logs or alert-rule behaviour on machines that
  don't use profiling. With no profiling relations, the rendered `config.alloy` must be
  byte-identical to today's.

## Constraints and facts already established

- gotodo release v0.1.0 is public at
  `https://github.com/ibrahim-dwellir/gotodo/releases/download/v0.1.0/`. The assets are
  `gotodo_v0.1.0_linux_amd64.tar.gz`, which unpacks to `gotodo_v0.1.0_linux_amd64/{gotodo,README.md}`,
  and `checksums.txt`, which uses sha256sum format. No token is needed: the repo is public.
- gotodo is configured only by env vars: `ADDR` (default `:8080`), `DB_PATH`, `JWT_SECRET`,
  `TOKEN_TTL` (default `24h`), `OPS_ADDR` (default `:6060`, `off` disables),
  `MUTEX_PROFILE_FRACTION` (default 5), `BLOCK_PROFILE_RATE` (default 5).
- gotodo has no `--version` flag. Health is `GET /api/health` on `ADDR`.
- The ops port serves `/metrics`, `/debug/pprof/{profile,heap,goroutine,mutex,block,...}` and
  `/debug/pprof/delta_{heap,mutex,block}`.
- **`machine_observability` lib** (`charms.dwellir_observability.v0.machine_observability`,
  LIBPATCH 5, canonical copy in `alloy-sub-operator`, vendor-copied by principals):
  - Payload v3 carries `charm_name`, `source_topology` (`SourceTopology(model, model_uuid,
    application, unit, charm_name)`), `metrics_endpoints` (`MetricsEndpoint(targets, path,
    scheme, ...)`), `systemd_units`, `journal_match_expressions`, `log_files` and
    `artifacts`. Artifacts are alert rules only; there are no dashboards.
  - `MachineObservabilityProvider(charm, payload_factory=..., refresh_events=...)` writes
    the payload into the **application** databag on relation-joined/changed and on
    config-changed/upgrade-charm.
  - Only the leader may write app data, and the reference charm doesn't guard that because
    it runs single-unit. gotodo must publish only when `self.unit.is_leader()`: wrap
    `payload_factory`/`publish`, or subclass the provider. Also republish on
    `leader_elected`.
- **Reference implementation:** `/home/ibrahim/Projects/dwellir-observability-reference/src/charm.py`.
  It shows `MachineObservabilityProvider` with a v3 payload factory, and
  `GrafanaDashboardProvider(self, relation_name="grafana-dashboard",
  dashboards_path="src/grafana_dashboard_templates")`. The templates dir is empty apart from
  a README. Dashboards are added programmatically with `add_dashboard(json)` after
  `remove_non_builtin_dashboards()`, with a deterministic UID from
  `dashboard_uid(model_uuid, app_name)`. Copy this pattern.
- **The `grafana_dashboard` lib** (`charms.grafana_k8s.v0.grafana_dashboard`, LIBPATCH 52 in
  the reference charm) only rewrites `prometheus` and `loki` datasources (to
  `${prometheusds}` and `${lokids}`), and leaves other types alone. Its regexes match
  `$datasource`, not `${datasource}`. `grafana-vm` and `grafana-k8s` consume the same
  schema.
- The gotodo profiles dashboard queries `memory:*` profile types. Whether the Alloy native
  path produces `memory:*` (expected) or something else is to be confirmed in Step 0.
- **`alloy-sub`:**
  - A subordinate on `ubuntu@22.04:amd64` and `ubuntu@24.04:amd64`, attached over
    `juju-info` (container scope).
  - Installs `alloy` from `apt.grafana.com stable`, unpinned.
  - Renders `config.alloy` in Python (`src/config_builder.py`), which today emits
    `prometheus.*` and `loki.*` blocks only.
  - Consumes `machine-observability` (lib `charms.dwellir_observability.v0.machine_observability`,
    LIBPATCH 5, schemas v1–v3) for metrics, journald, file logs and alert-rule artifacts.
  - It has no profiling support today. Iris doesn't provide `machine-observability`, which
    is why profiling uses a separate `pprof_scrape` endpoint rather than a v4 schema.
- **Iris's `pprof_scrape` provider** (`iris-operator/src/interface_profiling_source.py`) writes
  JSON under the unit data key `profiling_source`, version 1. It contains `service_name`,
  `targets` (loopback host:port), `profile_types` (Alloy block names: `process_cpu`, `memory`,
  `goroutine`, plus `mutex` and `block` when sampling is on) and `labels` (`juju_model`,
  `juju_model_uuid`, `juju_application`, `juju_unit`, `juju_charm`). Iris has no
  godeltaprof endpoints.
- **`pyroscope-vm`** (default `package-version` 1.21.0, which must be a 1.x of at least
  1.21.0):
  - Provides `profiling` (interface `profiling`) using Canonical's unchanged library,
    `charms.pyroscope_coordinator_k8s.v0.profiling` LIBPATCH 5.
  - Its leader publishes `<address>:<http port, default 4040>` with `insecure=True`, under
    the field name `otlp_grpc_endpoint_url`.
  - Pyroscope serves both OTLP gRPC and its native HTTP ingest (`/ingest`, and the push API
    `pyroscope.write` uses) on that one HTTP listener.
  - Its validation proved native pprof ingestion into 1.21.0.
  - It also provides `grafana-source` (datasource type `grafana-pyroscope-datasource`).
- **`ProfilingEndpointRequirer(relations).get_endpoints()`** returns entries with
  `.otlp_grpc` (host:port, no scheme) and `.insecure`.
- **Pyroscope 1.14.1** rejected resource `service.name` as a duplicate `service_name` label.
  The native path sets the `service_name` label directly, so this doesn't apply, but target
  1.21.0 or later.

## Part 1: `gotodo-operator`

### Replace the template

`src/charm.py`, `src/gotodo.py` and the tests are the stock template: demo secrets, a
`log-level` config and `api-token`/`pause`/`resume`. Remove all of that. Keep the repo
tooling (uv, tox, ruff, pyright, pytest, ops 3.x, jubilant integration tests). Keep the split
between `src/charm.py` (Juju concerns) and `src/gotodo.py` (workload functions with no ops
imports).

### charmcraft.yaml

- `name: gotodo-operator`. Fill in title, summary and description for real.
- `base: ubuntu@24.04`, `platforms: amd64:` only.
- `assumes: juju >= 3.6`.
- `provides:`
  - `machine-observability`: interface `machine_observability`, `scope: container`,
    `optional: true`.
  - `profiling-source`: interface `pprof_scrape`, `scope: container`, `optional: true`.
  - `grafana-dashboard`: interface `grafana_dashboard`, `optional: true`.
- No `requires`. `alloy-sub` attaches through gotodo's implicit `juju-info`.
- Libraries:
  - Vendor-copy from `alloy-sub-operator`, which holds the canonical copies:
    `charms.dwellir_observability.v0.machine_observability` and the new
    `charms.dwellir_observability.v0.pprof_scrape` (see Part 2).
  - Fetch `charms.grafana_k8s.v0.grafana_dashboard` with `charm-libs` (or vendor it the way
    the reference charm does).
  - Add every library's PYDEPS to `pyproject.toml` (`pydantic`, `cosl` for
    `grafana_dashboard`; check each lib's `PYDEPS`).

### Config options

| Option | Type | Default | Meaning |
|---|---|---|---|
| `version` | string | `v0.1.0` | GitHub release tag to install. Changing it upgrades or downgrades in place. |
| `port` | int | `8080` | Public UI/API port (`ADDR=:<port>`). The charm opens it with `open-port`. |
| `ops-port` | int | `6060` | Metrics and pprof port, always bound to `127.0.0.1` (`OPS_ADDR=127.0.0.1:<port>`). Never opened. |
| `token-ttl` | string | `24h` | `TOKEN_TTL`. |
| `mutex-profile-fraction` | int | `5` | `MUTEX_PROFILE_FRACTION`; `0` drops `godeltaprof_mutex` from the published profile types. |
| `block-profile-rate` | int | `5` | `BLOCK_PROFILE_RATE`; `0` drops `godeltaprof_block` from the published profile types. |

The download URL is derived as
`https://github.com/ibrahim-dwellir/gotodo/releases/download/<version>/gotodo_<version>_linux_amd64.tar.gz`.
The checksum file is `checksums.txt` beside it. Builder's call: whether to also expose the
repo or base URL as a hidden or advanced option.

### Filesystem, user, service

- **User:** create system user and group `gotodo` with no login shell, home `/opt/gotodo`,
  and no home skeleton.
- **`/opt/gotodo/`:** owned by `gotodo:gotodo`, mode 0755. It holds the binary at
  `/opt/gotodo/gotodo`, which is the tarball's inner `gotodo` flattened out of its versioned
  subdir, plus the release `README.md`. Install by downloading to a temp dir, verifying the
  sha256 against the `checksums.txt` line for that exact asset name, extracting, then
  atomically replacing `/opt/gotodo/gotodo`. Run `chown -R gotodo:gotodo /opt/gotodo` after
  every install. Refuse to extract archive members with absolute paths or `..`.
- **`/var/gotodo/`:** the SQLite database directory, owned by `gotodo:gotodo`, mode 0750.
  `DB_PATH=/var/gotodo/gotodo.db`. Never deleted by the charm, not even on remove.
- **`/etc/gotodo/gotodo.env`:** owned by `root:root`, mode 0600. systemd reads it, so the
  gotodo user can't edit its own config. It holds `ADDR`, `OPS_ADDR`, `DB_PATH`,
  `JWT_SECRET`, `TOKEN_TTL`, `MUTEX_PROFILE_FRACTION` and `BLOCK_PROFILE_RATE`.
- **JWT secret:** 32 random bytes as hex, from `secrets.token_hex(32)`. Generate it once per
  unit when the env file has no `JWT_SECRET`, and keep it across config changes, upgrades and
  restarts by reading it back from the env file. Per unit, not shared: each unit has its own
  database and users, so tokens don't need to work across units. Never log it.
- **`/etc/systemd/system/gotodo.service`:** `User=gotodo`, `Group=gotodo`,
  `EnvironmentFile=/etc/gotodo/gotodo.env`, `ExecStart=/opt/gotodo/gotodo`,
  `WorkingDirectory=/var/gotodo`, `Restart=on-failure`, `WantedBy=multi-user.target`.
  Builder's call: hardening directives such as `NoNewPrivileges`, `ProtectSystem=strict` with
  `ReadWritePaths=/var/gotodo`, and `PrivateTmp`.

### Lifecycle

- **install:** create the user and dirs, download and verify, write the env file and unit,
  `daemon-reload`, then enable and start.
- **config-changed / upgrade-charm:**
  - Re-render the env file and unit.
  - If `version` changed, re-download and verify. Skip the download when the installed
    version, recorded in `/opt/gotodo/.version` or in unit stored state, already matches.
  - Restart only if something actually changed.
  - Reconcile `open-port` with `port`.
  - Republish `profiling-source`.
- **start:** start unless a stop action has set "intended stopped" (see Actions).
- **Readiness:** after a start or restart, poll `GET http://127.0.0.1:<port>/api/health`
  for up to 30 s. A failure gives `BlockedStatus("gotodo did not become healthy; see journalctl -u gotodo")`.
- **Workload version:** the installed release tag.
- **Status:**
  - `ActiveStatus` when the service is running and healthy.
  - `MaintenanceStatus` while it installs or restarts.
  - `BlockedStatus` with a clear message for a download, checksum or health failure.
  - `ActiveStatus("stopped by action; run the start action")` while intentionally stopped. It
    is still active because it is operator intent, not a fault.
- **update-status:** a cheap check that the service is active and healthy. Never restarts it.
- **remove:** stop and disable the service, then remove the unit file and env file. Keep
  `/var/gotodo`, the data. Builder's call: whether to remove `/opt/gotodo` and the user.
- **Errors:** download failures (network or HTTP status) and checksum mismatches leave the
  previously installed binary untouched and running.

### Actions

Replace `pause`/`resume` with three actions, each without params:

- `start`: clear "intended stopped", start the service, wait for health, return the
  resulting state.
- `stop`: set "intended stopped", stop the service, return the state. Later hooks
  (config-changed, update-status, upgrade-charm) must not start it again.
- `restart`: clear "intended stopped", restart, wait for health, return the state.

Store "intended stopped" in unit-local state that survives charm upgrades, such as
`ops.StoredState` or a file under `/var/lib/juju`-adjacent charm state. Action failures
`event.fail(...)` with the reason.

### machine-observability (provider)

Follow `dwellir-observability-reference/src/charm.py`. Publish a v3
`MachineObservabilityPayload`:

```python
MachineObservabilityPayload(
    schema_version=3,
    charm_name=self.meta.name,
    source_topology=SourceTopology(model=..., model_uuid=..., application=self.app.name,
                                   unit=self.unit.name, charm_name=self.meta.name),
    metrics_endpoints=[MetricsEndpoint(targets=[f"localhost:{ops_port}"],
                                       path="/metrics", scheme="http")],
    systemd_units=["gotodo.service"],
    journal_match_expressions=[],
    log_files=[],
    artifacts=[],
)
```

- **Leader only:** the payload lives in the application databag, so only the leader
  publishes. Guard the provider's refresh/publish with `self.unit.is_leader()`, and
  republish on `leader_elected` and whenever `ops-port` changes.
- **Topology:** `source_topology.unit` is the leader's unit name. That's harmless, because
  `alloy-sub` takes per-unit topology from `juju-info`.
- **Metrics labels:** `alloy-sub` scrapes `localhost:<ops-port>` on every machine with
  `job=<principal app name>` (here `gotodo`) and adds Juju topology labels (`juju_unit`,
  `juju_application`, `juju_model`, ...). `instance` is the same `localhost:<port>` on every
  unit, so dashboards must tell units apart by `juju_unit`.
- No alert-rule artifacts in this iteration.

### grafana-dashboard (provider)

Follow `dwellir-observability-reference` exactly:

- `GrafanaDashboardProvider(self, relation_name="grafana-dashboard", dashboards_path="src/grafana_dashboard_templates")`,
  with that dir holding only a README.
- On every init: `remove_non_builtin_dashboards()`, then `add_dashboard(...)` once per
  dashboard JSON in `src/grafana_dashboards/`.
- Each dashboard gets a deterministic `uid` derived from `model_uuid`, the app name and the
  dashboard name, adapting the reference charm's `dashboard_uid` helper to two dashboards.
  Same-named apps in different models then stay distinct.

### Dashboards

Copy `../gotodo/deploy/grafana/gotodo-dashboard.json` and
`gotodo-profiles-dashboard.json` into `src/grafana_dashboards/`, adjusted for Juju-managed
Grafana:

- **Metrics dashboard:**
  - Change every panel and variable datasource of type `prometheus` from `${datasource}`
    to `${prometheusds}`, and drop the `datasource` template variable. The
    `grafana_dashboard` lib and Grafana inject `prometheusds` and the Juju topology
    dropdowns.
  - Replace the `instance` variable with one over `juju_unit`, because `instance` is
    `localhost:<port>` on every unit. `job` resolves to `gotodo`, so keep it or drop it in
    favour of `juju_application`, whichever reads cleaner.
  - Keep `route`.
- **Profiles dashboard:**
  - Keep its own `datasource` variable of type `grafana-pyroscope-datasource`, because the
    lib won't rewrite it. It must select the datasource `pyroscope-vm:grafana-source`
    provisions.
  - Point the `instance` variable at the label `alloy-sub` actually sets (`instance` =
    Juju unit, see Part 2).
  - Set the profile type IDs to what Step 0 observes in Pyroscope (expected `memory:*`),
    not to a guess.
- Add a short `src/grafana_dashboards/README.md` saying where the files came from and what
  was changed. The originals in the gotodo repo stay as they are.

### profiling-source (provider)

Use `PprofScrapeProvider` from the `pprof_scrape` lib (Part 2). Each unit publishes, under
unit data key `profiling_source`, as JSON:

```json
{
  "version": 1,
  "service_name": "gotodo",
  "targets": ["127.0.0.1:6060"],
  "profile_types": ["process_cpu", "godeltaprof_memory", "goroutine",
                    "godeltaprof_mutex", "godeltaprof_block"],
  "labels": {"juju_model": "...", "juju_model_uuid": "...", "juju_application": "gotodo",
             "juju_unit": "gotodo/0", "juju_charm": "gotodo-operator"}
}
```

- The target port follows `ops-port`.
- `godeltaprof_mutex` is listed only when `mutex-profile-fraction > 0`, and
  `godeltaprof_block` only when `block-profile-rate > 0`.
- The payload is withdrawn (the key removed) while the service is intentionally stopped or
  not installed.

### Tests

- **Unit tests (ops.testing / Scenario):**
  - Install renders the env file and unit with correct content and permissions. Mock
    filesystem, subprocess and HTTP at the `gotodo.py` boundary.
  - The JWT secret is generated once and preserved.
  - A version change triggers a download; an unchanged version doesn't.
  - A checksum mismatch blocks and keeps the old binary.
  - stop / start / restart actions, and "intended stopped" surviving config-changed and
    update-status.
  - `open-port` follows `port`.
  - The `machine-observability` app databag holds the v3 payload on the leader only, and
    follows `ops-port`.
  - The `grafana-dashboard` relation carries both dashboards with stable, distinct UIDs, and
    no `${datasource}` remains in the metrics dashboard.
  - The `profiling-source` payload, including the mutex/block toggles and withdrawal.
- **`gotodo.py` tests:** checksum parsing, tarball extraction safety, env-file rendering.
- **Integration (jubilant):**
  - Deploy on an LXD VM, active, `curl :8080/api/health`.
  - Run each action.
  - Relate `alloy-sub` (`juju-info` + `machine-observability`), and check that it goes
    active and its rendered `config.alloy` scrapes `localhost:6060/metrics` and reads the
    `gotodo.service` journal.
  - Builder's call how far to go toward real Mimir, Loki and Grafana in CI. A manual
    verification runbook in the README is acceptable for that end.

## Part 2: profiling in `alloy-sub-operator`

### Step 0: spike (throwaway, before any profiling code)

On one LXD VM, with a reachable Pyroscope 1.21.0 (a `pyroscope-vm` unit, or Pyroscope 1.21.0
from Grafana's APT repo on the same VM):

1. Run gotodo with its defaults.
2. Install `alloy` from `apt.grafana.com`, the same way `alloy-sub` does.
3. Write a `config.alloy` by hand with:
   - a `pyroscope.write` to `http://<pyroscope>:4040`;
   - a `pyroscope.scrape` for gotodo, with `service_name="gotodo"`, enabling
     `process_cpu`, `godeltaprof_memory`, `godeltaprof_mutex`, `godeltaprof_block` and
     `goroutine`, and disabling everything else;
   - a second `pyroscope.scrape` for the same gotodo, with `service_name="gotodo-plain"`,
     enabling only the plain `memory`, `mutex` and `block`. This simulates Iris, which has
     no delta endpoints.
4. Generate some load against `:8080` for about 10 minutes and record:
   - that every enabled type arrives for both services;
   - the exact profile type IDs Pyroscope lists, which go into the shipped profiles
     dashboard;
   - whether the target label `instance` set to `gotodo/0` survives, or whether Alloy
     overwrites it with `127.0.0.1:6060`;
   - **whether `gotodo-plain`'s alloc, mutex and block values stay roughly flat under steady
     load (deltas) or keep growing (cumulative).** I expect Alloy and Pyroscope to handle
     this, but it hasn't been verified.

**If `gotodo-plain` keeps growing:** stop and report back to the user before building the
`alloy-sub` consumer. It decides how Iris's plain types are handled, and that is the user's
call.

### charmcraft.yaml additions

```yaml
requires:
  profiling-source:
    interface: pprof_scrape
    scope: container
    optional: true
    description: pprof targets the principal publishes for Alloy to pull (e.g. iris, gotodo).
  send-profiles:
    interface: profiling
    optional: true
    limit: 1
    description: |
      Pyroscope to push profiles to, using Pyroscope's native ingest on the advertised
      host:port. Relate to pyroscope-vm:profiling. Not compatible with OTLP-only receivers
      such as opentelemetry-collector:receive-profiles.
```

Add `charm-libs` (or a vendored copy, matching how the repo already handles
`grafana_cloud_integrator`) for `charms.pyroscope_coordinator_k8s.v0.profiling`, and add its
PYDEPS. Bases stay at 22.04 and 24.04 amd64.

### `pprof_scrape` library (owned here)

Add `lib/charms/dwellir_observability/v0/pprof_scrape.py`, next to `machine_observability`,
with the same "canonical source lives in alloy-sub-operator, vendor-copy elsewhere" docstring.
It needs a new LIBID, `LIBAPI = 0` and `LIBPATCH = 1`.

- **Payload model, v1, exactly Iris's wire format:** unit data key `profiling_source`,
  holding a JSON object with `version: 1`, `service_name: str`, `targets: list[str]`
  (`host:port`), `profile_types: list[str]` and `labels: dict[str, str]`.
- **`PROFILE_TYPES` vocabulary:** Alloy `pyroscope.scrape` block names: `process_cpu`,
  `memory`, `goroutine`, `mutex`, `block`, `fgprof`, `godeltaprof_memory`,
  `godeltaprof_mutex` and `godeltaprof_block`.
- **`PprofScrapeProvider(charm, relation_name)`:** a generalised version of Iris's
  `ProfilingSourceProvider`. `set_source(service_name, targets, profile_types)` publishes the
  payload, with the `labels` filled from the unit's Juju topology. `set_source(None)`
  withdraws it. It republishes on `relation_joined`.
- **`PprofScrapeRequirer(charm, relation_name)`:** `get_sources()` returns validated
  payloads from the remote principal unit. A payload is skipped with a warning log when its
  version isn't 1 or its JSON or shape is malformed. A target is dropped with a warning when
  it isn't loopback (`127.0.0.0/8`, `::1`, `localhost`). Unknown profile types are dropped
  with a warning. Iris's own provider must decode through this requirer unchanged; a unit
  test covers that with Iris's exact payload.

### Config rendering (`src/config_builder.py`)

**When rendering happens:** only when there is at least one valid source with at least one
target **and** a `send-profiles` endpoint. Otherwise emit no `pyroscope.*` blocks at all. The
existing output must not change for machines without profiling (a golden test pins this).

**Write block:** one per configuration.

```alloy
pyroscope.write "pyroscope" {
  endpoint {
    url = "http://<host:port>"      // https:// when the endpoint is not insecure
  }
}
```

`<host:port>` is `ProfilingEndpointRequirer(...).get_endpoints()[0].otlp_grpc`. That field is
named for OTLP, but on `pyroscope-vm` it is the address of Pyroscope's single HTTP listener,
which also serves native ingest. Put this assumption in a code comment and in the README.

**Scrape blocks:** one per source:

```alloy
pyroscope.scrape "<sanitized service_name>_<sanitized juju_unit>" {
  targets = [
    {"__address__" = "127.0.0.1:6060", "service_name" = "gotodo", "instance" = "gotodo/0",
     "juju_model" = "...", "juju_model_uuid" = "...", "juju_application" = "gotodo",
     "juju_unit" = "gotodo/0", "juju_charm" = "gotodo-operator"},
  ]
  forward_to      = [pyroscope.write.pyroscope.receiver]
  scrape_interval = "<profiles-scrape-interval>"
  profiling_config {
    profile.process_cpu        { enabled = true }
    profile.memory             { enabled = false }
    profile.godeltaprof_memory { enabled = true }
    // ...every type in PROFILE_TYPES rendered explicitly, true only if listed in the payload
  }
}
```

- Every type is rendered explicitly as enabled or disabled. Alloy enables several types by
  default, and only what the principal lists should be pulled.
- **Topology:** follow `alloy-sub`'s existing rule, under which the attached `juju-info`
  principal is the source of truth. Juju topology from `juju-info` overrides the payload's
  `labels` on conflict. Other payload labels are passed through.
- **`instance` label:** use the Juju unit name, so units on different machines that all scrape
  `127.0.0.1:6060` stay distinct. If Step 0 shows Alloy overwrites `instance`, use whatever
  Alloy mechanism keeps it (for example a `discovery.relabel` in front), and record the
  choice.
- **Config option:** add `profiles-scrape-interval` (string, default `"15s"`), named the way
  the repo names its existing interval options. Alloy derives the CPU profile duration from
  it.
- **Reload:** reuse `alloy-sub`'s existing write-validate-reload path. Don't add a second
  one.

### Charm wiring (`src/charm.py`)

- Observe `profiling-source` and `send-profiles` relation events and reconcile the config,
  the same way the existing relations do.
- **Status:** a source with no `send-profiles` endpoint, or `send-profiles` with no source,
  isn't an error. Follow the repo's existing pattern for "partially wired". If it already
  reports such states in the status message, add a short profiling note there. Otherwise
  log only.
- **No leader-only writes:** the consumer only reads the principal's unit data and
  Pyroscope's app data, so every unit works the same. This is unaffected by the
  shared-subordinate rule-aggregation issue described in the repo's untracked
  `2026-08-27` spec.

### README

Add a "Profiling" section covering:

- the two relations and the example `juju relate` lines;
- that `send-profiles` expects Pyroscope's own `profiling` endpoint, and that the collector
  charm's `receive-profiles` doesn't work, with the reason;
- the loopback-only target rule;
- the profile type vocabulary;
- a link to Iris and gotodo as providers.

### Tests

- **`config_builder` unit tests:**
  - A golden test with no profiling relations: the output is byte-identical to the
    pre-change output.
  - A gotodo payload, an Iris payload, and both on the same render.
  - Explicit enabled/disabled rendering for every type.
  - Unknown types and non-loopback targets dropped.
  - Topology override on label conflict.
  - The `insecure=False` endpoint giving `https://`.
  - Component-name sanitisation for unit names with `/`.
- **`pprof_scrape` library tests:** a provider/requirer round trip, Iris's literal payload,
  malformed and wrong-version payloads, and withdrawal.
- **Charm tests (Scenario):** relation-changed and relation-broken reconcile the config.
  Nothing renders without `send-profiles`.
- **Integration:** extend the repo's existing integration suite.
  - Deploy a principal publishing `pprof_scrape`: the packed `gotodo-operator` from the
    sibling repo, or a minimal test-fixture principal charm. Builder's call; the fixture is
    preferred if packing gotodo in CI is awkward.
  - Deploy `pyroscope-vm`, packed from `/home/ibrahim/Projects/pyroscope-vm-operator` or its
    edge release.
  - Assert Pyroscope lists `service_name=gotodo` and each enabled profile type, using the
    Pyroscope label and profile-type query API.

## Decisions made by the user

- Profiles are handled by `alloy-sub` (Grafana Alloy), not a new helper charm or logic
  inside the gotodo charm. This avoids a second collector on the machine.
- `alloy-sub` pushes directly to `pyroscope-vm:profiling`, not through
  `opentelemetry-collector`.
- `alloy-sub` consumes Iris's existing `profiling-source` / `pprof_scrape` endpoint
  unchanged.
- No `opentelemetry-collector` and no `cos-agent`. Metrics and journal logs go through
  `alloy-sub` over `machine-observability`.
- `profiling-source` stays a separate endpoint, because Iris only supports that one. An
  operator can relate `machine-observability`, `profiling-source` or both.
- Dashboards ship over a direct `grafana-dashboard` relation, as in
  `dwellir-observability-reference`.
- The binary comes from GitHub releases, linux amd64, and is unpacked into `/opt/gotodo/`.
- The `gotodo` user owns `/opt/gotodo` and runs the systemd service.
- The actions are `start`, `stop` and `restart`.
- Both dashboards from `gotodo/deploy/grafana/` ship with the charm.
- The JWT secret is randomly generated.
- The SQLite database directory is `/var/gotodo`.

## Calls made by me (Claude), open to correction

- The `pprof_scrape` lib lives at `charms.dwellir_observability.v0.pprof_scrape` in
  `alloy-sub`, and gotodo vendors it.
- `alloy-sub`'s endpoint names are `profiling-source` and `send-profiles`, matching Iris's
  name and the collector charm's naming respectively.
- `pyroscope-vm`'s advertised `otlp_grpc` address is reused as the native ingest base URL.
- The `godeltaprof_*` profile type names in the v1 payload, rather than a v2 schema.
- Stop and report if Step 0 shows Iris's plain cumulative profiles keep growing.
- The JWT secret is per unit and lives in a root-only env file, not a Juju secret.
- `ops-port` is always bound to loopback. Only `port` is opened.
- The version comes from a `version` config option (default `v0.1.0`), not a Juju resource.
- "Intended stopped" survives hooks, following Iris's behaviour.
- Journal logs for `gotodo.service` are included in `machine-observability`.
- Dashboard copies are adjusted for Juju-managed Grafana inside the charm. The originals in the gotodo repo
  are left alone.
- `/var/gotodo` is kept on remove.
- No alert rules or traces for gotodo in this iteration.

## Open items for the builder

- Confirm that the Alloy version `apt.grafana.com stable` currently installs supports every
  block in `PROFILE_TYPES`, especially the `godeltaprof_*` blocks.
- Confirm the dashboard variable behaviour in a real Grafana. The profiles dashboard's
  `datasource` variable must pick up the datasource `pyroscope-vm:grafana-source` provisions.
- Plan how the vendored `pprof_scrape` copy in gotodo is kept in sync, for example a
  `make`/`tox` check comparing it with the sibling `alloy-sub` copy.
