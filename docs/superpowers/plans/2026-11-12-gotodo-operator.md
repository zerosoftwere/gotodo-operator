# gotodo-operator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Juju machine charm that installs the gotodo binary from GitHub releases, runs it as the `gotodo` user under systemd with start/stop/restart actions, and publishes three things: metrics and journal over `machine-observability`, pprof targets over `profiling-source`, and both dashboards over `grafana-dashboard`.

**Architecture:**
- `src/gotodo.py` holds the workload functions: release download and verify, filesystem, env and unit rendering, systemd, health. It has no ops imports, and every external effect is injectable for tests.
- `src/charm.py` holds one idempotent `_reconcile()` driven by install, config-changed, upgrade-charm and start, plus actions, update-status and remove. It owns the three relation providers.
- `src/dashboards.py` loads and registers the bundled dashboards.

**Tech Stack:** Python ≥3.10, ops ~=3.8, ops.testing (Scenario), pydantic 2, cosl, uv, tox, ruff, pyright, jubilant.

**Spec:** `/home/ibrahim/tut/spike/pyroscope/gotodo-operator/docs/superpowers/specs/2026-11-12-gotodo-charm-and-alloy-sub-profiling-design.md` (Part 1)

**Repo:** `/home/ibrahim/tut/spike/pyroscope/gotodo-operator`. It has no commits yet. Task 1 creates branch `feat/gotodo-charm` and makes the first commit there.

**Depends on:** `alloy-sub` plan Task 2 for the `pprof_scrape` library (needed by Task 7 here) and Task 1 for the spike note (needed by Task 8 here). Tasks 1–6 can run before those exist.

## Global Constraints

- `base: ubuntu@24.04`; `platforms: amd64:` only; `assumes: juju >= 3.6`.
- Release URL: `https://github.com/ibrahim-dwellir/gotodo/releases/download/<version>/gotodo_<version>_linux_amd64.tar.gz`. Checksums are in `checksums.txt` beside it, in sha256sum format. The binary is inside the tarball at `gotodo_<version>_linux_amd64/gotodo`.
- Paths:
  - binary `/opt/gotodo/gotodo`, with installed version in `/opt/gotodo/.version`; `/opt/gotodo` is owned by `gotodo:gotodo`, mode 0755;
  - data `/var/gotodo`, owned by `gotodo:gotodo`, mode 0750, with `DB_PATH=/var/gotodo/gotodo.db`;
  - env `/etc/gotodo/gotodo.env`, owned by `root:root`, mode 0600;
  - unit `/etc/systemd/system/gotodo.service`.
- Env keys: `ADDR=:<port>`, `OPS_ADDR=127.0.0.1:<ops-port>`, `DB_PATH`, `JWT_SECRET`, `TOKEN_TTL`, `MUTEX_PROFILE_FRACTION`, `BLOCK_PROFILE_RATE`.
- The JWT secret is `secrets.token_hex(32)`, generated once per unit and preserved by reading it back from the env file. It must never be logged or returned.
- Config options: `version` (string, `v0.1.0`), `port` (int, `8080`), `ops-port` (int, `6060`), `token-ttl` (string, `24h`), `mutex-profile-fraction` (int, `5`), `block-profile-rate` (int, `5`).
- Actions `start`, `stop` and `restart` take no params.
- Health is `GET http://127.0.0.1:<port>/api/health` returning 200, polled for up to 30 s.
- Status strings, exact:
  - `MaintenanceStatus("installing gotodo <version>")`
  - `MaintenanceStatus("restarting gotodo")`
  - `BlockedStatus("download of gotodo <version> failed; see juju debug-log")`
  - `BlockedStatus("checksum mismatch for gotodo <version>")`
  - `BlockedStatus("gotodo did not become healthy; see journalctl -u gotodo")`
  - `BlockedStatus("gotodo is not running; run the restart action")`
  - `ActiveStatus("stopped by action; run the start action")`
  - `ActiveStatus("")`
- Provides (all `optional: true`): `machine-observability` (`machine_observability`, `scope: container`), `profiling-source` (`pprof_scrape`, `scope: container`), `grafana-dashboard` (`grafana_dashboard`).
- Vendored libs, as exact copies pinned by sha256 in `tests/unit/test_library_policy.py`:
  - `lib/charms/dwellir_observability/v0/machine_observability.py` from `/home/ibrahim/Projects/alloy-sub-operator/lib/...` (sha256 `f93196c38bbd8343b1d72173e860e1adf5ddf04ce728fae36d6e57fc3916e679`);
  - `lib/charms/dwellir_observability/v0/pprof_scrape.py` from the alloy-sub branch `feat/pprof-profiling`;
  - `lib/charms/grafana_k8s/v0/grafana_dashboard.py` from `/home/ibrahim/Projects/dwellir-observability-reference/lib/...` (LIBPATCH 52).
- Remove keeps `/var/gotodo`.
- Run checks with `tox -e format,lint,unit` from the repo root.

## Review Focus

1. **Re-running config-changed with nothing changed:** no download, no restart, no status flap. Pinned by `test_reconcile_is_idempotent_without_changes` (Task 4).
2. **Changing `port` on a running unit:** the env is re-rendered, the service restarts, the new port opens and the old one closes, and health is checked on the new port. Pinned by `test_port_change_restarts_and_moves_open_port` (Task 4).
3. **Config change after install:** `JWT_SECRET` survives, so issued tokens stay valid. Pinned by `test_env_rerender_preserves_jwt_secret` (Task 2) and `test_config_change_keeps_jwt_secret` (Task 4).
4. **`stop` action followed by config-changed, upgrade-charm or update-status:** the service stays stopped and the profiling target is withdrawn. Pinned by `test_intended_stopped_survives_hooks` (Task 5) and `test_profiling_withdrawn_while_stopped` (Task 7).
5. **A non-leader unit:** must not write `machine-observability` app data or crash. Pinned by `test_non_leader_does_not_publish_machine_observability` (Task 6).

---

### Task 1: Scaffold: metadata, config, actions, vendored libs, empty charm

**Files:**
- Modify: `charmcraft.yaml` (full rewrite), `pyproject.toml` (dependencies), `README.md` (title and summary placeholder)
- Delete the template bodies: `src/charm.py` and `src/gotodo.py` are replaced, and `tests/unit/test_charm.py` and `tests/integration/test_charm.py` are emptied to module docstrings.
- Create: `lib/charms/dwellir_observability/v0/machine_observability.py`, `lib/charms/grafana_k8s/v0/grafana_dashboard.py` (copies), `tests/unit/test_library_policy.py`, `tests/unit/test_metadata.py`

**Interfaces:**
- Produces: `GotodoOperatorCharm(ops.CharmBase)` in `src/charm.py`, which only observes `install`, sets `ActiveStatus("")` and has `ops.main(...)`. Later tasks extend it.

- [ ] **Step 1: Create the branch.** `git switch -c feat/gotodo-charm`.
- [ ] **Step 2: Write the failing tests.**
  - `tests/unit/test_metadata.py` parses `charmcraft.yaml` with `yaml.safe_load` and asserts:
    - `test_platforms_amd64_only`: `platforms` keys are `["amd64"]` and `base == "ubuntu@24.04"`;
    - `test_provides_interfaces`: the three provides with the interfaces and scopes from Global Constraints, and no `requires` key;
    - `test_config_defaults`: each option's type and default as in Global Constraints;
    - `test_actions`: the set is `{"start","stop","restart"}`.
  - `tests/unit/test_library_policy.py` adds `test_<lib>_matches_canonical_source` per vendored lib (the two present now), comparing sha256 against the source file's current hash. Compute it with `sha256sum` on the source path and paste it in.
- [ ] **Step 3: Run the tests to see them fail.** `uv run --group unit pytest tests/unit/test_metadata.py tests/unit/test_library_policy.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement the scaffold.**
  - Rewrite `charmcraft.yaml`: real title, summary and description; the template's `parts` kept; `config` and `actions` per Global Constraints, each with a one-paragraph description.
  - Copy both libs.
  - In `pyproject.toml`, set `dependencies = ["ops~=3.8", "pydantic>=2,<3", "cosl>=1.10.3,<2"]`, and add `pyyaml` to the `unit` group.
  - Replace `src/charm.py` with the minimal charm and `src/gotodo.py` with a module docstring.
  - Run `uv lock`.
- [ ] **Step 5: Run the checks.** `tox -e format,lint,unit`. Expected: PASS (pyright included).
- [ ] **Step 6: Commit.** This is the first commit: template baseline plus scaffold.

```bash
git add .gitignore CONTRIBUTING.md LICENSE README.md charmcraft.yaml pyproject.toml uv.lock tox.ini src tests lib docs/superpowers
git commit -m "feat: scaffold gotodo-operator metadata, config, actions and vendored libs"
```

### Task 2: Workload: release download, verify, install; env and unit rendering

**Files:**
- Modify: `src/gotodo.py`
- Create: `tests/unit/test_gotodo_install.py`, `tests/unit/test_gotodo_files.py`

**Interfaces:**
- Produces, used by Tasks 3–4:
  - Errors: `class InstallError(Exception)`; `class DownloadError(InstallError)`; `class ChecksumError(InstallError)`; `class ArchiveError(InstallError)`.
  - `OPT_DIR = Path("/opt/gotodo")`, `DATA_DIR = Path("/var/gotodo")`, `ENV_PATH = Path("/etc/gotodo/gotodo.env")`, `UNIT_PATH = Path("/etc/systemd/system/gotodo.service")`, `SERVICE = "gotodo"`.
  - `release_urls(version: str) -> tuple[str, str]`, returning (tarball URL, checksums URL).
  - `parse_checksum(checksums_text: str, asset_name: str) -> str`. Raises `ChecksumError` if the asset isn't listed.
  - `install_release(version: str, *, opt_dir: Path = OPT_DIR, fetch: Callable[[str], bytes] = fetch_url) -> None`. It fetches both URLs, verifies the sha256, safely extracts the binary and README, `os.replace`s them into `opt_dir`, writes `opt_dir/".version"`, and sets binary mode 0755. It doesn't chown; that's Task 3.
  - `installed_version(opt_dir: Path = OPT_DIR) -> str | None`.
  - `fetch_url(url: str) -> bytes`: urllib with a 60 s timeout, raising `DownloadError` on any URL or HTTP error.
  - `@dataclass(frozen=True) class Settings: port: int; ops_port: int; token_ttl: str; mutex_profile_fraction: int; block_profile_rate: int`.
  - `render_env(settings: Settings, jwt_secret: str) -> str`. Keys in Global Constraints order, one `KEY=value` per line.
  - `read_env(env_path: Path = ENV_PATH) -> dict[str, str]`. Returns `{}` if the file is missing.
  - `load_or_create_jwt_secret(env_path: Path = ENV_PATH) -> str`.
  - `write_file_if_changed(path: Path, content: str, *, mode: int) -> bool`. It creates parent dirs and returns whether the content changed.
  - `render_unit() -> str`: `[Unit]` `Description=GoTodo`, `After=network-online.target`, `Wants=network-online.target`; `[Service]` `User=gotodo`, `Group=gotodo`, `EnvironmentFile=/etc/gotodo/gotodo.env`, `WorkingDirectory=/var/gotodo`, `ExecStart=/opt/gotodo/gotodo`, `Restart=on-failure`, `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ReadWritePaths=/var/gotodo`, `PrivateTmp=yes`; `[Install]` `WantedBy=multi-user.target`.

- [ ] **Step 1: Write the failing tests.** Build fixture tarballs in `tmp_path` with `tarfile`.
  - `test_release_urls_v0_1_0`: the exact two URLs for `v0.1.0`.
  - `test_parse_checksum_finds_asset` / `test_parse_checksum_missing_asset_raises`. Use the real line `342bcab0e4d3cef60c229525045cb467ba068cd10a2465875f4fd21539eb5449  gotodo_v0.1.0_linux_amd64.tar.gz`.
  - `test_install_release_writes_binary_and_version`: a fake `fetch` returns the fixture tarball and a matching checksums text. Asserts `opt_dir/"gotodo"` has the content and mode 0o755, and that `installed_version()` is `"v0.1.0"`.
  - `test_install_release_checksum_mismatch_keeps_old_binary`: a pre-existing `opt_dir/gotodo` with `b"old"`, and a bad checksum, give `ChecksumError` with the content still `b"old"`.
  - `test_install_release_rejects_path_traversal`: a tarball member `../evil` or `/abs` gives `ArchiveError`, and nothing is written outside `opt_dir`.
  - `test_install_release_missing_binary_member_raises_archive_error`.
  - `test_fetch_error_propagates_as_download_error`: the fake `fetch` raises `DownloadError`.
  - `test_render_env_contains_exact_keys`: `Settings(8080,6060,"24h",5,5)` with secret `"s"` gives the exact 7-line text, including `OPS_ADDR=127.0.0.1:6060` and `DB_PATH=/var/gotodo/gotodo.db`.
  - `test_load_or_create_jwt_secret_generates_64_hex`, and `test_env_rerender_preserves_jwt_secret` (write the env, call again, get the same secret).
  - `test_write_file_if_changed_sets_mode_and_reports_change`: first call True with mode 0o600, second call with the same content False.
  - `test_render_unit_runs_as_gotodo`: asserts the `User=`, `EnvironmentFile=`, `ExecStart=` and `ReadWritePaths=` lines.
- [ ] **Step 2: Run the tests to see them fail.** `uv run --group unit pytest tests/unit/test_gotodo_install.py tests/unit/test_gotodo_files.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement the functions** in `src/gotodo.py`. Extract by reading only the two expected member names; reject any member whose normalised path is absolute or contains `..`. Stage in a `tempfile.TemporaryDirectory(dir=opt_dir.parent)` so `os.replace` stays on one filesystem.
- [ ] **Step 4: Run the tests to see them pass.** Same command. Expected: PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/gotodo.py tests/unit/test_gotodo_install.py tests/unit/test_gotodo_files.py
git commit -m "feat(workload): download, verify and install gotodo releases; render env and unit"
```

### Task 3: Workload: user, ownership, systemd, health

**Files:**
- Modify: `src/gotodo.py`
- Create: `tests/unit/test_gotodo_system.py`

**Interfaces:**
- Produces, used by Tasks 4–5. All shell-outs go through `_run(argv: list[str]) -> subprocess.CompletedProcess`, so tests patch `gotodo._run`.
  - `ensure_user() -> None`. Runs `getent passwd gotodo`; if it fails, runs `useradd --system --user-group --home-dir /opt/gotodo --no-create-home --shell /usr/sbin/nologin gotodo`.
  - `ensure_dirs(*, opt_dir: Path = OPT_DIR, data_dir: Path = DATA_DIR) -> None`. Creates both with modes 0755 and 0750, then runs `chown -R gotodo:gotodo` on each.
  - `daemon_reload()`, `enable()`, `start()`, `stop()`, `restart()`, `disable()`, each `-> None`. They run `systemctl <verb> gotodo` (`daemon_reload` runs `systemctl daemon-reload`).
  - `is_active() -> bool`: `systemctl is-active --quiet gotodo` with return code 0.
  - `service_state() -> dict[str, str]`: `systemctl show gotodo --property=ActiveState,SubState,MainPID`, returned as `{"active-state","sub-state","main-pid"}`.
  - `wait_healthy(port: int, *, timeout: float = 30.0, interval: float = 1.0, probe: Callable[[str], int] = http_status, sleep: Callable[[float], None] = time.sleep) -> bool`.
  - `http_status(url: str) -> int`. Returns 0 on a connection error.
  - `remove_service(*, unit_path: Path = UNIT_PATH, env_path: Path = ENV_PATH) -> None`. Runs `stop`, then `disable` (ignoring failures), deletes both files and runs `daemon_reload`.

- [ ] **Step 1: Write the failing tests.**
  - `test_ensure_user_creates_when_missing` and `test_ensure_user_noop_when_present`: assert the exact `useradd` argv, or that it wasn't called.
  - `test_ensure_dirs_modes_and_chown`: `tmp_path` dirs get modes 0o755 and 0o750, and `chown -R gotodo:gotodo <dir>` is called twice.
  - `test_systemctl_verbs`: the argv for each verb.
  - `test_service_state_parses_show_output`: stdout `"ActiveState=active\nSubState=running\nMainPID=42\n"` gives `{"active-state":"active","sub-state":"running","main-pid":"42"}`.
  - `test_wait_healthy_true_after_retries`: the probe returns 0, then 0, then 200, giving True with a fake `sleep`.
  - `test_wait_healthy_times_out`: always 503 gives False, with no more than `timeout/interval + 1` probes.
  - `test_wait_healthy_probes_expected_url`: `http://127.0.0.1:9090/api/health`.
  - `test_remove_service_deletes_files_and_tolerates_stop_failure`.
- [ ] **Step 2: Run the tests to see them fail.** `uv run --group unit pytest tests/unit/test_gotodo_system.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** in `src/gotodo.py`. `_run` uses `subprocess.run(argv, check=False, capture_output=True, text=True)`. Callers that require success raise `subprocess.CalledProcessError` on a non-zero exit. The exceptions are `is_active`, `getent`, and stop/disable inside `remove_service`.
- [ ] **Step 4: Run the tests to see them pass.** Same command. Expected: PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/gotodo.py tests/unit/test_gotodo_system.py
git commit -m "feat(workload): manage gotodo user, ownership, systemd unit and health checks"
```

### Task 4: Charm lifecycle and reconcile

**Files:**
- Modify: `src/charm.py`
- Create: `tests/unit/test_charm_lifecycle.py`

**Interfaces:**
- Consumes: everything from Tasks 2–3 via `import gotodo`. Tests patch `charm.gotodo.<fn>`.
- Produces, used by Tasks 5–8:
  - `GotodoOperatorCharm._stored` (`ops.StoredState`) with `intended_stopped: bool = False`.
  - `GotodoOperatorCharm._settings() -> gotodo.Settings`.
  - `GotodoOperatorCharm._reconcile() -> None`.
  - `GotodoOperatorCharm._running() -> bool`, true when installed, not intended stopped, and `gotodo.is_active()`.
  - `GotodoOperatorCharm._refresh_relations() -> None`. A no-op hook here; Tasks 6–8 fill it in.

`_reconcile` order:
1. `ensure_user`.
2. If `installed_version() != version`: set Maintenance `installing gotodo <version>` and `install_release(version)`. Catch `DownloadError` and `ArchiveError` → Blocked "download …"; catch `ChecksumError` → Blocked "checksum …". In both cases return, leaving the old binary running.
3. `ensure_dirs`.
4. `load_or_create_jwt_secret` and `write_file_if_changed(ENV_PATH, render_env(...), mode=0o600)`.
5. `write_file_if_changed(UNIT_PATH, render_unit(), mode=0o644)`. If changed, `daemon_reload` and `enable`.
6. `self.unit.set_ports(port)`.
7. `set_workload_version(version)`.
8. If `intended_stopped`: Active "stopped by action; run the start action". Otherwise, if anything changed (binary, env or unit) or the service isn't active: Maintenance "restarting gotodo", `restart()`, then `wait_healthy(port)`, which gives Active `""` or Blocked "did not become healthy".
9. `_refresh_relations()`.

Hooks: `install`, `config_changed`, `upgrade_charm` and `start` call `_reconcile`. `update_status` only checks: intended stopped gives Active "stopped by action; run the start action"; not active gives Blocked "gotodo is not running; run the restart action"; active but `wait_healthy(port, timeout=5)` false gives Blocked "did not become healthy"; otherwise Active `""`. It never restarts. `remove` calls `remove_service()`.

- [ ] **Step 1: Write the failing tests.** Use `testing.Context(GotodoOperatorCharm)` and a fixture that patches every `charm.gotodo` side-effect function with `MagicMock`s. The default is `installed_version` returning `None` and then `"v0.1.0"`, `is_active` True, `wait_healthy` True, and `write_file_if_changed` True.
  - `test_install_installs_and_becomes_active`: `install_release("v0.1.0")` is called, `restart` is called, the status is `ActiveStatus("")`, `workload_version == "v0.1.0"`, and `opened_ports == {TCPPort(8080)}`.
  - `test_reconcile_is_idempotent_without_changes`: `installed_version` returns `"v0.1.0"` and `write_file_if_changed` returns False, so config-changed calls neither `install_release` nor `restart`, and the status is Active.
  - `test_version_change_reinstalls_and_restarts`: config `version="v0.2.0"` gives `install_release("v0.2.0")` and `restart`.
  - `test_download_failure_blocks_and_does_not_restart`: `install_release` raises `DownloadError` → the exact Blocked string, and `restart` isn't called.
  - `test_checksum_failure_blocks`.
  - `test_unhealthy_after_restart_blocks`.
  - `test_port_change_restarts_and_moves_open_port`: the input state has `opened_ports={TCPPort(8080)}` and config `port=9090`, giving `opened_ports == {TCPPort(9090)}`, `restart` called and `wait_healthy(9090)`.
  - `test_config_change_keeps_jwt_secret`: `load_or_create_jwt_secret` returns `"abc"` and `render_env` is called with `"abc"`. It asserts that `"abc"` is in no log record (`caplog`).
  - `test_update_status_never_restarts` (active and healthy → Active; inactive → Blocked "not running").
  - `test_remove_calls_remove_service`.
- [ ] **Step 2: Run the tests to see them fail.** `uv run --group unit pytest tests/unit/test_charm_lifecycle.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `_settings`, `_reconcile`, the hook handlers and `_refresh_relations` (empty) in `src/charm.py`, per the order above.
- [ ] **Step 4: Run the checks.** `tox -e lint,unit`. Expected: PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/charm.py tests/unit/test_charm_lifecycle.py
git commit -m "feat(charm): reconcile install, config, upgrade, start, update-status and remove"
```

### Task 5: start / stop / restart actions

**Files:**
- Modify: `src/charm.py`
- Create: `tests/unit/test_charm_actions.py`

**Interfaces:**
- Consumes: `_stored.intended_stopped`, `_reconcile`, `gotodo.start/stop/restart/wait_healthy/service_state`.
- Produces: action results with exactly the keys `active-state`, `sub-state` and `main-pid`.

- [ ] **Step 1: Write the failing tests.**
  - `test_stop_action_stops_and_sets_intent`: `gotodo.stop` is called, the status is `ActiveStatus("stopped by action; run the start action")`, and the results contain `active-state`.
  - `test_start_action_clears_intent_and_waits_healthy`: from a stored `intended_stopped=True`, `start` and `wait_healthy` are called and the status is `ActiveStatus("")`.
  - `test_restart_action_restarts`.
  - `test_start_action_fails_when_unhealthy`: `wait_healthy` False raises `testing.ActionFailed`, with a message containing `did not become healthy`.
  - `test_intended_stopped_survives_hooks`: a parametrised loop over `config_changed`, `upgrade_charm`, `update_status` and `start`, all with stored `intended_stopped=True`. Neither `restart` nor `start` is called, and the status stays "stopped by action…".
- [ ] **Step 2: Run the tests to see them fail.** `uv run --group unit pytest tests/unit/test_charm_actions.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the three handlers. Each sets or clears intent, acts, then calls `event.set_results(gotodo.service_state())`, and on unhealthy, `event.fail("gotodo did not become healthy; see journalctl -u gotodo")`. Each calls `_refresh_relations()` afterwards. Remove the template's `pause`/`resume` observers.
- [ ] **Step 4: Run the checks.** `tox -e lint,unit`. Expected: PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/charm.py tests/unit/test_charm_actions.py
git commit -m "feat(actions): add start, stop and restart actions with sticky stop intent"
```

### Task 6: `machine-observability` provider (leader only)

**Files:**
- Modify: `src/charm.py`
- Create: `tests/unit/test_machine_observability.py`

**Interfaces:**
- Consumes: `MachineObservabilityProvider`, `MachineObservabilityPayload`, `MetricsEndpoint` and `SourceTopology` from `charms.dwellir_observability.v0.machine_observability`.
- Produces: `GotodoOperatorCharm._machine_observability_payload() -> MachineObservabilityPayload`, the exact v3 payload from spec Part 1 "machine-observability (provider)", with `metrics_endpoints[0].targets == [f"localhost:{ops_port}"]` and `systemd_units == ["gotodo.service"]`.

- [ ] **Step 1: Write the failing tests.** The relation is `testing.Relation("machine-observability", remote_app_name="alloy-sub")`.
  - `test_leader_publishes_v3_payload`: `leader=True`, config-changed. App databag `payload` JSON has `schema_version == 3`, `metrics_endpoints[0].targets == ["localhost:6060"]`, `systemd_units == ["gotodo.service"]` and `source_topology.application == "gotodo-operator"`.
  - `test_payload_follows_ops_port`: `ops-port=7070` gives `["localhost:7070"]`.
  - `test_non_leader_does_not_publish_machine_observability`: `leader=False` runs without an exception, and the local app databag is empty.
  - `test_leader_elected_republishes`.
- [ ] **Step 2: Run the tests to see them fail.** `uv run --group unit pytest tests/unit/test_machine_observability.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Construct `MachineObservabilityProvider(self, payload_factory=self._leader_payload, refresh_events=[self.on.config_changed, self.on.upgrade_charm, self.on.leader_elected])`. `_leader_payload` returns the payload, but the lib's `publish()` writes unconditionally, so wrap it: subclass `MachineObservabilityProvider` locally as `_LeaderOnlyMachineObservabilityProvider`, overriding `_on_refresh` and `publish` to return early when `not self.model.unit.is_leader()`. Don't edit the vendored lib. Call `self._mo.publish(self._machine_observability_payload())` from `_refresh_relations` (the guard applies).
- [ ] **Step 4: Run the checks.** `tox -e lint,unit`. Expected: PASS.
- [ ] **Step 5: Commit.**

```bash
git add src/charm.py tests/unit/test_machine_observability.py
git commit -m "feat: publish metrics and journal sources over machine-observability"
```

### Task 7: `profiling-source` provider

**Files:**
- Create: `lib/charms/dwellir_observability/v0/pprof_scrape.py` (an exact copy from `/home/ibrahim/Projects/alloy-sub-operator` branch `feat/pprof-profiling`)
- Modify: `tests/unit/test_library_policy.py` (add its hash), `src/charm.py`
- Create: `tests/unit/test_profiling_source.py`

**Interfaces:**
- Consumes: `PprofScrapeProvider(charm, "profiling-source", source_factory=...)`, `PprofSource` and `RELATION_KEY` (alloy-sub plan Task 2).
- Produces: `GotodoOperatorCharm._pprof_source() -> PprofSource | None`. This is `None` when not installed or intended stopped. Otherwise it is `PprofSource("gotodo", (f"127.0.0.1:{ops_port}",), types)`, where `types` = `("process_cpu", "godeltaprof_memory", "goroutine")`, plus `"godeltaprof_mutex"` when `mutex-profile-fraction > 0`, plus `"godeltaprof_block"` when `block-profile-rate > 0`.

- [ ] **Step 1: Copy the library** and add `test_pprof_scrape_matches_canonical_source`, with the sha256 of the alloy-sub copy.
- [ ] **Step 2: Write the failing tests.** The relation is `testing.SubordinateRelation("profiling-source", remote_app_name="alloy-sub")`.
  - `test_publishes_gotodo_payload`: the unit data `profiling_source` JSON has `service_name == "gotodo"`, `targets == ["127.0.0.1:6060"]`, and `profile_types == ["process_cpu","godeltaprof_memory","goroutine","godeltaprof_mutex","godeltaprof_block"]`.
  - `test_zero_fraction_and_rate_drop_mutex_and_block`.
  - `test_profiling_withdrawn_while_stopped`: the stop action leaves no `profiling_source` key, and a later config-changed still has none.
  - `test_target_follows_ops_port`.
- [ ] **Step 3: Run the tests to see them fail.** `uv run --group unit pytest tests/unit/test_profiling_source.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement.** Construct the provider in `__init__` with `source_factory=self._pprof_source`, and call its `publish()` from `_refresh_relations`.
- [ ] **Step 5: Run the checks.** `tox -e lint,unit`. Expected: PASS.
- [ ] **Step 6: Commit.**

```bash
git add lib/charms/dwellir_observability/v0/pprof_scrape.py tests/unit/test_library_policy.py src/charm.py tests/unit/test_profiling_source.py
git commit -m "feat: publish pprof targets over profiling-source"
```

### Task 8: Dashboards over `grafana-dashboard`

**Files:**
- Create: `src/grafana_dashboards/gotodo-dashboard.json` and `src/grafana_dashboards/gotodo-profiles-dashboard.json` (adapted copies), `src/grafana_dashboards/README.md`, `src/grafana_dashboard_templates/README.md`, `src/dashboards.py`, `tests/unit/test_dashboards.py`
- Modify: `src/charm.py`

**Interfaces:**
- Consumes: `GrafanaDashboardProvider` from `charms.grafana_k8s.v0.grafana_dashboard`, and `DashboardPath40UID` from `cosl`. The spike note `docs/superpowers/spikes/2026-11-12-alloy-pyroscope-spike.md` supplies the profile type IDs.
- Produces:
  - `dashboards.load_dashboards(model_uuid: str, app_name: str, *, root: Path = Path(__file__).parent / "grafana_dashboards") -> list[str]`. Each JSON string has `uid = DashboardPath40UID.generate(model_uuid, f"{app_name}/{path.stem}")`, serialised with `sort_keys=True` and compact separators.
  - `GotodoOperatorCharm._register_dashboards() -> None`, called in `__init__`.

- [ ] **Step 1: Write the failing tests.**
  - `test_metrics_dashboard_has_no_datasource_variable`: the text contains no `${datasource}`. Every panel or target `datasource.uid` that was Prometheus is now `${prometheusds}`, and the `templating.list` names include `juju_unit` and `route` and exclude `datasource` and `instance`.
  - `test_profiles_dashboard_keeps_pyroscope_datasource_variable`: a `datasource` variable of type `grafana-pyroscope-datasource` exists, and every `profileTypeId` in the file is in the spike note's "Profile type IDs" list. Hard-code that list into the test from the note.
  - `test_load_dashboards_sets_distinct_stable_uids`: two dashboards, distinct UIDs, the same UIDs on a second call, and different UIDs for a different `model_uuid`.
  - `test_grafana_dashboard_relation_carries_two_dashboards`: Scenario with `testing.Relation("grafana-dashboard", remote_app_name="grafana")` and `leader=True`. The local app data `dashboards` JSON has 2 entries in `templates`.
- [ ] **Step 2: Run the tests to see them fail.** `uv run --group unit pytest tests/unit/test_dashboards.py -v`. Expected: FAIL.
- [ ] **Step 3: Adapt the dashboards.** Copy them from `/home/ibrahim/tut/spike/pyroscope/gotodo/deploy/grafana/` and apply the spec Part 1 "Dashboards" edits. In the metrics dashboard, replace the `instance` variable query with `label_values(gotodo_http_requests_in_flight{juju_application=~"$juju_application"}, juju_unit)`, named `juju_unit`, and change every `instance=~"$instance"` matcher to `juju_unit=~"$juju_unit"`. Write `src/grafana_dashboards/README.md`, saying where the files came from (the gotodo repo path and commit `1d50887`) and listing each edit.
- [ ] **Step 4: Implement** `src/dashboards.py`, plus `GrafanaDashboardProvider(self, relation_name="grafana-dashboard", dashboards_path="src/grafana_dashboard_templates")`, then `remove_non_builtin_dashboards()` and `add_dashboard(text)` for each dashboard, the same as `dwellir-observability-reference/src/charm.py:_register_current_dashboard`.
- [ ] **Step 5: Run the checks.** `tox -e lint,unit`. Expected: PASS.
- [ ] **Step 6: Commit.**

```bash
git add src/grafana_dashboards src/grafana_dashboard_templates src/dashboards.py src/charm.py tests/unit/test_dashboards.py
git commit -m "feat: ship gotodo metrics and profiles dashboards over grafana-dashboard"
```

### Task 9: README and integration tests

**Files:**
- Modify: `README.md`, `tests/integration/test_charm.py`

**Interfaces:**
- Consumes: the packed charm (`charmcraft pack`), and optionally `ALLOY_SUB_CHARM_PATH` (for example `/home/ibrahim/Projects/alloy-sub-operator/alloy-sub_ubuntu@24.04-amd64.charm`, or a fresh pack of the branch).

- [ ] **Step 1: Write the README.**
  - What the charm does.
  - The config table from Global Constraints.
  - Actions.
  - The relation table (three provides).
  - The exact `juju relate` block from spec Part 1 "Target topology".
  - Paths (`/opt/gotodo`, `/var/gotodo`, `/etc/gotodo/gotodo.env`), with a note that `/var/gotodo` survives removal.
  - That the ops port is loopback-only.
  - A manual verification runbook: Mimir query `gotodo_http_requests_total{juju_application="gotodo"}`; Loki `{juju_application="gotodo"}`; Pyroscope `service_name=gotodo`; Grafana dashboards "GoTodo" and "GoTodo profiles".
- [ ] **Step 2: Write the integration tests** in `tests/integration/test_charm.py`. Deploy with `base="ubuntu@24.04"`, `constraints={"virt-type": "virtual-machine"}`, `app="gotodo"`.
  - `test_deploy_active`: `juju.wait(jubilant.all_active)`.
  - `test_health_endpoint`: `juju.exec("curl -fsS http://127.0.0.1:8080/api/health", unit="gotodo/0")` succeeds.
  - `test_files_and_owner`: `stat -c '%U %a' /opt/gotodo /var/gotodo /etc/gotodo/gotodo.env` gives `gotodo 755`, `gotodo 750` and `root 600`.
  - `test_ops_port_is_loopback_only`: `ss -ltn` shows `127.0.0.1:6060` and no `0.0.0.0:6060` or `*:6060`.
  - `test_stop_start_restart_actions`: run `stop` and check the status message; run `start` and get active; run `restart` and get active.
  - `test_alloy_sub_scrapes_metrics_and_journal`: skip unless `ALLOY_SUB_CHARM_PATH` is set. Deploy it and relate `alloy-sub:juju-info gotodo` and the `machine-observability` endpoints. Assert that `/etc/alloy/config.alloy` on `gotodo/0` contains `localhost:6060` and `gotodo.service`.
- [ ] **Step 3: Pack and run.** `charmcraft pack && tox -e integration`. Expected: PASS. If no Juju controller is available, say so in the hand-off; don't claim a pass.
- [ ] **Step 4: Commit.**

```bash
git add README.md tests/integration/test_charm.py
git commit -m "docs: document gotodo-operator; add integration tests"
```
