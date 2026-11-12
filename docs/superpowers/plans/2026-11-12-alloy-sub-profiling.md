# alloy-sub pprof Profiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `alloy-sub` pulls Go pprof profiles from any principal that publishes `pprof_scrape` on `profiling-source` (gotodo, Iris), and pushes them to `pyroscope-vm` with Alloy's `pyroscope.scrape` → `pyroscope.write`.

**Architecture:** A new vendorable library, `charms.dwellir_observability.v0.pprof_scrape`, defines Iris's v1 wire format (provider and requirer). `ConfigBuilder` gains `pyroscope.*` rendering that only kicks in when a source and a sink both exist. `AlloySubCharm` reads the principal's `profiling-source` unit data plus `pyroscope-vm`'s `profiling` app data (Canonical `ProfilingEndpointRequirer`), and treats profiling sources as a valid pipeline on their own.

**Tech Stack:** Python 3, ops 3.x, ops.testing (Scenario), pydantic 2, Grafana Alloy from apt.grafana.com, uv/tox, ruff, pyright.

**Spec:** `/home/ibrahim/tut/spike/pyroscope/gotodo-operator/docs/superpowers/specs/2026-11-12-gotodo-charm-and-alloy-sub-profiling-design.md` (Part 2)

**Repo:** `/home/ibrahim/Projects/alloy-sub-operator`. Work on branch `feat/pprof-profiling`, created from `main`.

## Global Constraints

- Never touch, stage, commit or delete the untracked `docs/superpowers/specs/2026-08-27-shared-subordinate-rule-aggregation-design.md` or `docs/superpowers/plans/2026-08-27-shared-subordinate-rule-aggregation.md`. Stage files by explicit path only, never `git add -A` or `git add .`.
- Bases stay `ubuntu@22.04:amd64` and `ubuntu@24.04:amd64`.
- The wire format is exactly Iris v1: unit data key `profiling_source`, JSON `{"version": 1, "service_name", "targets", "profile_types", "labels"}`.
- `PROFILE_TYPES` = `("process_cpu", "memory", "goroutine", "mutex", "block", "fgprof", "godeltaprof_memory", "godeltaprof_mutex", "godeltaprof_block")`.
- Profiling targets must be loopback (`127.0.0.0/8`, `::1`, `localhost`).
- With no profiling relations, rendered `config.alloy` is byte-identical to `main`'s output.
- The push URL is `http://<otlp_grpc host:port>`, or `https://` when the endpoint isn't `insecure`.
- New config option: `profiles_scrape_interval`, string, default `"15s"`. Underscore naming, matching `global_scrape_interval`.
- New relations: `profiling-source` (`pprof_scrape`, `scope: container`, optional) and `send-profiles` (`profiling`, optional, `limit: 1`).
- Every file under `lib/` must be declared in `dependencies/vendored.json` (and `upstreams.json`) with its sha256, or `tests/unit/test_dependency_bom.py` fails.
- Run checks with `tox -e lint,static,unit` from the repo root.

## Review Focus

1. **Iris-only principal** (`juju-info` + `profiling-source` + `send-profiles`, no `machine-observability`): must render profiles and go active, not reset to "waiting for machine-observability relation". Pinned by `test_profiling_only_principal_is_a_valid_pipeline` (Task 4).
2. **Existing machines with no profiling relations:** the config is byte-identical to before. Pinned by `test_build_without_profiling_matches_main_golden` (Task 3).
3. **`send-profiles` removed while running:** the `pyroscope.*` blocks disappear, the rest of the config stays, and Alloy reloads. Pinned by `test_send_profiles_broken_removes_pyroscope_blocks` (Task 4).
4. **A payload with one bad target or unknown type:** only the bad item is dropped and the rest renders. Pinned by `test_requirer_drops_bad_targets_and_types_keeps_rest` (Task 2).
5. **Unit and service names with `/`, `-` or `.`:** Alloy component names stay valid and unique per source. Pinned by `test_pyroscope_component_names_are_sanitized_and_unique` (Task 3).

---

### Task 1: Spike: Alloy → Pyroscope 1.21.0 profile behaviour (throwaway)

No product code. This produces a findings note that Task 3 and the gotodo plan's dashboard task read.

**Files:**
- Create: `/home/ibrahim/tut/spike/pyroscope/gotodo-operator/docs/superpowers/spikes/2026-11-12-alloy-pyroscope-spike.md`

- [ ] **Step 1: Set up a VM.** Create an LXD VM (`lxc launch ubuntu:24.04 alloy-spike --vm`). Copy `/home/ibrahim/tut/spike/pyroscope/gotodo/dist/v0.1.0/gotodo_v0.1.0_linux_amd64/gotodo` in, and run it with `JWT_SECRET=spike OPS_ADDR=127.0.0.1:6060 ./gotodo &`.
- [ ] **Step 2: Install Pyroscope 1.21.0.** On the same VM, install it from apt.grafana.com (`apt-get install pyroscope=1.21.0`) and start it on `:4040`. Alternatively, use an existing `pyroscope-vm` unit and its address.
- [ ] **Step 3: Install Alloy.** Install `alloy` exactly the way `src/alloy.py:install` does, then write `/etc/alloy/config.alloy` with:
  - one `pyroscope.write "pyroscope" { endpoint { url = "http://127.0.0.1:4040" } }`;
  - `pyroscope.scrape "gotodo"` with target `{"__address__" = "127.0.0.1:6060", "service_name" = "gotodo", "instance" = "gotodo/0"}`, enabling `process_cpu`, `godeltaprof_memory`, `godeltaprof_mutex`, `godeltaprof_block` and `goroutine`, with every other type explicitly `enabled = false`;
  - `pyroscope.scrape "gotodo_plain"`, same address, `service_name = "gotodo-plain"`, enabling only `memory`, `mutex` and `block`.
  Use `scrape_interval = "15s"`. Run `alloy fmt` and restart Alloy.
- [ ] **Step 4: Generate load and observe.** Drive load for 10 minutes (a loop of register, login and create-todo calls, from the gotodo README curl example). Then query Pyroscope: `curl -s -XPOST localhost:4040/querier.v1.QuerierService/ProfileTypes -H 'content-type: application/json' -d '{}'` and `.../LabelValues` with `{"name":"instance"}`.
- [ ] **Step 5: Record findings.** Write the spike file with exactly these headings:
  - `## Profile type IDs`: the full list for `service_name=gotodo`;
  - `## instance label`: kept as `gotodo/0`, or overwritten;
  - `## Cumulative endpoints (gotodo-plain)`: flat or growing, with the numbers seen at minute 2 and minute 10 for `memory:alloc_space`, `mutex:delay` and `block:delay`;
  - `## Alloy version`: the `alloy --version` output.
- [ ] **Step 6: Gate.** If `gotodo-plain` values keep growing under steady load, **stop**: report to the user and don't start Task 4. If `instance` was overwritten, note that Task 3 Step 3 must use the relabel variant.
- [ ] **Step 7: Clean up.** Delete the VM with `lxc delete --force alloy-spike`. If the gotodo-operator branch `feat/gotodo-charm` already exists, commit the note there (`git add docs/superpowers/spikes/2026-11-12-alloy-pyroscope-spike.md && git commit -m "docs: record alloy to pyroscope profiling spike"`). Otherwise leave it uncommitted; gotodo plan Task 1 commits all of `docs/superpowers`.

### Task 2: `pprof_scrape` library

**Files:**
- Create: `lib/charms/dwellir_observability/v0/pprof_scrape.py`
- Create: `tests/unit/test_pprof_scrape.py`
- Modify: `tests/unit/test_library_policy.py` (add a hash pin)
- Modify: `dependencies/vendored.json`, `dependencies/upstreams.json`

**Interfaces:**
- Produces, consumed by Task 4 and by the gotodo plan:
  - `RELATION_KEY = "profiling_source"`, `PAYLOAD_VERSION = 1`, `PROFILE_TYPES: tuple[str, ...]` (Global Constraints order).
  - `@dataclass(frozen=True) class PprofSource: service_name: str; targets: tuple[str, ...]; profile_types: tuple[str, ...]; labels: dict[str, str] = field(default_factory=dict); unit_name: str = ""`.
  - `class PprofScrapeProvider(ops.Object)`, constructed as `__init__(self, charm, relation_name: str = "profiling-source", *, source_factory: Callable[[], PprofSource | None])`. It publishes on `relation_joined`/`relation_changed`, and `publish() -> None` writes or removes `RELATION_KEY` in **this unit's** data on every relation. `labels` are filled from topology: `juju_model`, `juju_model_uuid`, `juju_application`, `juju_unit`, `juju_charm`.
  - `class PprofScrapeRequirer(ops.Object)`, constructed as `__init__(self, charm, relation_name: str = "profiling-source")`. `get_sources() -> list[PprofSource]` reads every remote unit's `RELATION_KEY`, with `unit_name` set to the remote unit.
  - `is_loopback(target: str) -> bool`.
- The factory design (rather than a stored target) mirrors `MachineObservabilityProvider(payload_factory=...)`. The spec says `set_source`; this is that, as a callable.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_pprof_scrape.py`, using `testing.Context` with a minimal `CharmBase` declaring `provides: profiling-source` (provider) or `requires: profiling-source` (requirer), both `scope: container`:
  - `test_provider_publishes_iris_compatible_payload`: the factory returns `PprofSource("gotodo", ("127.0.0.1:6060",), ("process_cpu","goroutine"))`. Asserts the local unit data `profiling_source` JSON equals `{"version":1,"service_name":"gotodo","targets":["127.0.0.1:6060"],"profile_types":["process_cpu","goroutine"],"labels":{...5 juju_* keys...}}`.
  - `test_provider_withdraws_when_factory_returns_none`: the key is absent.
  - `test_requirer_decodes_iris_literal_payload`: remote unit data is exactly the README payload from `iris-operator` (`service_name "iris"`, `["process_cpu","memory","goroutine"]`). Asserts one `PprofSource` with those values and `unit_name == "iris/0"`.
  - `test_requirer_skips_wrong_version_and_malformed_json`: `version: 2` gives `[]`; `"{"` gives `[]`; both log a warning (`caplog`).
  - `test_requirer_drops_bad_targets_and_types_keeps_rest`: targets `["127.0.0.1:6060","10.0.0.5:6060"]` and types `["process_cpu","bogus"]` give targets `("127.0.0.1:6060",)` and types `("process_cpu",)`.
  - `test_requirer_skips_source_with_no_valid_targets`.
  - `test_is_loopback`: true for `127.0.0.1:6060`, `127.5.0.1:1`, `[::1]:6060` and `localhost:6060`; false for `0.0.0.0:6060` and `10.0.0.5:6060`.
- [ ] **Step 2: Run the tests to see them fail.** `uv run pytest tests/unit/test_pprof_scrape.py -v`. Expected: FAIL with `ModuleNotFoundError: charms.dwellir_observability.v0.pprof_scrape`.
- [ ] **Step 3: Implement the library.** Include a module docstring saying "Canonical source lives in alloy-sub-operator; vendor-copy into principals", and a usage example for both sides. Set `LIBID` to a fresh `uuid4().hex`, `LIBAPI = 0`, `LIBPATCH = 1`, `PYDEPS = ["pydantic>=2"]`. Validate with a pydantic model (`extra="ignore"`, so future fields don't break v1 readers).
- [ ] **Step 4: Run the tests to see them pass.** `uv run pytest tests/unit/test_pprof_scrape.py -v`. Expected: PASS.
- [ ] **Step 5: Pin the library.** Add `test_pprof_scrape_library_matches_canonical_source` to `tests/unit/test_library_policy.py`, with the file's sha256 (`sha256sum lib/charms/dwellir_observability/v0/pprof_scrape.py`).
  - Add a `vendored.json` entry with `path`, `sha256`, `library{LIBID,LIBAPI,LIBPATCH}`, `"scope": "runtime"`, `upstream_path` = same path, `"repository": "https://github.com/dwellir-public/alloy-sub-operator"`, `"commit": null`, `"license": "Apache-2.0"`, `"upstream_owner_repository": "https://github.com/dwellir-public/alloy-sub-operator"`, `"upstream_base_commit": null`, and `"modifications": "None: authored here; this repository is the canonical source."`.
  - Add a matching `upstreams.json` key `pprof_scrape` with role `runtime-vendored`.
  - If `tools/dependency_bom.py` rejects a `null` commit, read its validation and use the value it accepts for a locally authored library. Record that choice in the commit message.
- [ ] **Step 6: Run the checks.** `tox -e lint,static,unit`. Expected: all pass, including `test_dependency_bom.py`.
- [ ] **Step 7: Commit.**

```bash
git switch -c feat/pprof-profiling
git add lib/charms/dwellir_observability/v0/pprof_scrape.py tests/unit/test_pprof_scrape.py tests/unit/test_library_policy.py dependencies/vendored.json dependencies/upstreams.json
git commit -m "feat(lib): add pprof_scrape library compatible with iris profiling-source"
```

### Task 3: Render `pyroscope.*` blocks in `ConfigBuilder`

**Files:**
- Modify: `src/config_builder.py`
- Create: `tests/unit/fixtures/golden_no_profiling.alloy`
- Modify: `tests/unit/test_config_builder.py`

**Interfaces:**
- Consumes: `PROFILE_TYPES` from Task 2. Import it from `charms.dwellir_observability.v0.pprof_scrape`, adding `lib` to `sys.path` in tests the way `test_observability_relation.py` does.
- Produces, consumed by Task 4:
  - `@dataclass(frozen=True) class ProfilingSource: service_name: str; targets: list[str]; labels: dict[str, str]; profile_types: list[str]`. `labels` already contains `instance` and the Juju topology, merged by the charm.
  - New `ConfigBuilder.__init__` kwargs, all defaulted: `profiling_sources: list[ProfilingSource] | None = None`, `profiling_sink_url: str | None = None`, `profiles_scrape_interval: str = "15s"`.

- [ ] **Step 1: Capture the golden file before changing any code.** Write a throwaway script that builds a `ConfigBuilder` with the same kwargs as `test_build_renders_remote_write_metrics`, plus loki endpoints, systemd units and `host_metrics=HostMetrics(topology_labels={...})`. Write `build()` to `tests/unit/fixtures/golden_no_profiling.alloy`.
- [ ] **Step 2: Write the failing tests** in `tests/unit/test_config_builder.py`:
  - `test_build_without_profiling_matches_main_golden`: the same kwargs, rendered, equal the golden file byte for byte.
  - `test_build_omits_pyroscope_without_sink`: sources given, `profiling_sink_url=None`, so `"pyroscope." not in config`.
  - `test_build_omits_pyroscope_without_sources`.
  - `test_build_renders_pyroscope_write_and_scrape`: one source, `ProfilingSource(service_name="gotodo", targets=["127.0.0.1:6060"], labels={"juju_application": "gotodo", "juju_unit": "gotodo/0", "instance": "gotodo/0"}, profile_types=["process_cpu", "godeltaprof_memory", "goroutine"])`, with sink `http://10.0.0.9:4040`. It asserts:
    - `'pyroscope.write "pyroscope" {'` and `'url = "http://10.0.0.9:4040"'` are present;
    - `'pyroscope.scrape "gotodo_gotodo_0" {'`, `'"__address__" = "127.0.0.1:6060"'`, `'"service_name" = "gotodo"'` and `'"instance" = "gotodo/0"'` are present;
    - `'forward_to      = [pyroscope.write.pyroscope.receiver]'` (match whitespace-insensitively with a regex) is present;
    - `'scrape_interval = "15s"'` is present;
    - for all 9 `PROFILE_TYPES`, a `profile.<type> {` line exists with `enabled = true` exactly for the listed ones.
  - `test_build_renders_one_scrape_per_source`: gotodo and iris sources give two `pyroscope.scrape` blocks and one `pyroscope.write`.
  - `test_pyroscope_component_names_are_sanitized_and_unique`: `service_name="my.svc-x"` with `labels["juju_unit"]="app-1/12"` gives component `my_svc_x_app_1_12`. Two sources differing only in unit get distinct names.
  - `test_profiles_scrape_interval_is_rendered`: `"30s"`.
- [ ] **Step 3: Run the tests to see them fail.** `uv run pytest tests/unit/test_config_builder.py -v -k "pyroscope or profil or golden"`. Expected: the new tests FAIL (unknown kwarg) and the golden test passes.
- [ ] **Step 4: Implement the rendering.** Add `_render_pyroscope_write()` and `_render_pyroscope_scrape(source)` in `src/config_builder.py`, appended at the end of `build()`'s block list when both `profiling_sources` and `profiling_sink_url` are truthy.
  - The component name is `_sanitize_component_name(f"{service_name}_{labels.get('juju_unit','')}")`.
  - Target labels are `{"__address__": t, "service_name": service_name, **labels}`, one map per target, rendered in sorted key order through the existing `_render_key`/JSON quoting helpers.
  - Render every `PROFILE_TYPES` entry inside `profiling_config { }`.
  - **If the Task 1 spike recorded that `instance` is overwritten:** render a `discovery.relabel "<component>"` that sets `instance` from a `__meta_instance` label, and point `targets` at its output. Add one test for it.
- [ ] **Step 5: Run the tests to see them pass.** `uv run pytest tests/unit/test_config_builder.py -v`. Expected: all PASS, including every pre-existing test.
- [ ] **Step 6: Validate with real Alloy if available.** If `alloy` is installed locally, run `alloy fmt` on the output of `test_build_renders_one_scrape_per_source` (dump it to a temp file). Expected: exit 0. If Alloy isn't installed, note that in the commit message; the charm's `verify_config` covers it at runtime.
- [ ] **Step 7: Commit.**

```bash
git add src/config_builder.py tests/unit/test_config_builder.py tests/unit/fixtures/golden_no_profiling.alloy
git commit -m "feat(config): render pyroscope scrape and write blocks for profiling sources"
```

### Task 4: Charm wiring for `profiling-source` and `send-profiles`

**Files:**
- Modify: `charmcraft.yaml` (two `requires` entries and the `profiles_scrape_interval` option)
- Create: `lib/charms/pyroscope_coordinator_k8s/v0/profiling.py`, an exact copy of `/home/ibrahim/Projects/pyroscope-vm-operator/lib/charms/pyroscope_coordinator_k8s/v0/profiling.py` (LIBPATCH 5)
- Modify: `dependencies/vendored.json`, `dependencies/upstreams.json`, `src/charm.py`
- Create: `tests/unit/test_profiling_relation.py`

**Interfaces:**
- Consumes: `PprofScrapeRequirer` and `PprofSource` (Task 2); `ProfilingSource` and the new `ConfigBuilder` kwargs (Task 3); `ProfilingEndpointRequirer(relations).get_endpoints()`, giving `.otlp_grpc: str` and `.insecure: bool`.
- Produces, as methods on `AlloySubCharm`:
  - `_profiling_sources(principal_context: PrincipalContext) -> list[ProfilingSource]`;
  - `_profiling_sink_url() -> str | None`;
  - `_has_profiling_sources() -> bool`.

- [ ] **Step 1: Edit `charmcraft.yaml`.** Add exactly the two `requires` entries from spec Part 2 ("charmcraft.yaml additions"), and `profiles_scrape_interval` (type string, default `"15s"`, description: "How often Alloy pulls each pprof profile from profiling-source targets. CPU profiles sample for slightly less than this.").
- [ ] **Step 2: Vendor the `profiling` library** and declare it in both manifests:
  - `"upstream_owner_repository": "https://github.com/canonical/pyroscope-operators"`;
  - `"repository": "https://github.com/dwellir-public/pyroscope-vm-operator"`;
  - `"modifications": "None: exact copy."`;
  - add `cosl`/`pydantic` to PYDEPS only if the lib's own `PYDEPS` requires them and `pyproject.toml` lacks them.
- [ ] **Step 3: Write the failing tests** in `tests/unit/test_profiling_relation.py`. Reuse the patch set from `tests/unit/test_charm.py::test_start_becomes_active_when_required_relations_present` (patch `charm.ConfigBuilder` and assert on its call kwargs):
  - `test_profiling_only_principal_is_a_valid_pipeline`:
    - relations are `juju-info` (`remote_app_name="iris"`), `profiling-source` (a `SubordinateRelation` whose remote unit data is Iris's literal payload) and `send-profiles` (`remote_app_data={"otlp_grpc_endpoint_url": json.dumps("10.0.0.9:4040"), "insecure": json.dumps(True)}`);
    - `start` gives `ActiveStatus`, not Waiting;
    - `ConfigBuilder` receives `profiling_sink_url="http://10.0.0.9:4040"` and one `ProfilingSource(service_name="iris", targets=["127.0.0.1:6060"], ...)`, with `labels["instance"] == "iris/0"`.
  - `test_profiling_sink_https_when_not_insecure`: `insecure` false gives `"https://10.0.0.9:4040"`.
  - `test_profiling_without_send_profiles_renders_no_sink`: `profiling_sink_url=None`, and the status is unchanged from today's behaviour for the other relations.
  - `test_juju_info_topology_overrides_payload_labels`: the payload has `labels.juju_application="spoofed"` and `juju-info` is `iris`, giving `labels["juju_application"] == "iris"`. Extra payload labels such as `"team":"x"` are kept.
  - `test_send_profiles_broken_removes_pyroscope_blocks`: a `relation_broken` on `send-profiles` gives a `ConfigBuilder` call with `profiling_sink_url=None`, and `alloy.reload` is called.
  - `test_profiles_scrape_interval_option_passed_through`: config `profiles_scrape_interval="30s"`.
  - `test_machine_observability_behaviour_unchanged_without_profiling`: `_ready_state(with_loki=True)` from `test_charm.py`, with `ConfigBuilder` called with `profiling_sources=[]` and `profiling_sink_url=None`, and the same status string as today.
- [ ] **Step 4: Run the tests to see them fail.** `uv run pytest tests/unit/test_profiling_relation.py -v`. Expected: FAIL.
- [ ] **Step 5: Implement the wiring in `src/charm.py`.**
  - Add `"profiling-source"` and `"send-profiles"` to the relation-event observe loop (`src/charm.py:260-271`), plus `profiling-source` `relation_departed`.
  - Implement the three methods. In `_profiling_sources`, the labels are `{**source.labels, **principal_context.juju_labels(charm_name=<payload charm or source label>), "instance": principal_context.unit}`.
  - Pass the new kwargs into `ConfigBuilder(...)` in `_configure`.
  - In both `_configure` (the `not self._has_machine_observability_relation() and not self._has_local_sources()` check) and `_missing_relation_requirements`, add `and not self._has_profiling_sources()`.
  - In `_active_message`, add `("profiles", self._has_profiling_sources())` to the sources list.
  - When sources exist but there's no sink, emit `logger.info("profiling sources present but no send-profiles relation; profiles not forwarded")` and leave the status alone.
- [ ] **Step 6: Run the full suite.** `tox -e lint,static,unit`. Expected: all pass. Pre-existing `test_charm.py` tests may need `profiling_sources`/`profiling_sink_url` added to asserted `ConfigBuilder` kwargs; add them, but don't change their expected statuses.
- [ ] **Step 7: Commit.**

```bash
git add charmcraft.yaml lib/charms/pyroscope_coordinator_k8s/v0/profiling.py dependencies/vendored.json dependencies/upstreams.json src/charm.py tests/unit/test_profiling_relation.py tests/unit/test_charm.py
git commit -m "feat: pull pprof profiles from profiling-source and push to send-profiles"
```

### Task 5: README and integration test

**Files:**
- Modify: `README.md`, and `ARCHITECTURE.md` if it lists relations
- Modify: `tests/integration/test_charm.py`

**Interfaces:**
- Consumes: everything above. The packed gotodo charm comes from the gotodo plan, or a fixture principal.

- [ ] **Step 1: Add a "Profiling" section to the README.** Cover the relation table rows, the `juju relate` lines from spec Part 1 "Target topology" (alloy-sub lines only), loopback-only targets, the `PROFILE_TYPES` vocabulary, that `send-profiles` expects Pyroscope's own `profiling` endpoint (native push on the advertised host:port), and that `opentelemetry-collector:receive-profiles` doesn't work, with the reason. Add `test_readme_documents_profiling` to `tests/unit/test_repo_baseline.py`, asserting the `"## Profiling"` heading and `"profiling-source"` appear.
- [ ] **Step 2: Add the integration test** `test_profiling_reaches_pyroscope`, gated on env `GOTODO_CHARM_PATH` and `PYROSCOPE_CHARM_PATH` (skip when unset):
  - deploy gotodo, `alloy-sub` and `pyroscope-vm`;
  - relate `juju-info`, `profiling-source` and `send-profiles`;
  - wait for all to be active;
  - poll for up to 3 minutes until `curl -s -XPOST http://<pyroscope>:4040/querier.v1.QuerierService/LabelValues -d '{"name":"service_name"}'` contains `gotodo`.
- [ ] **Step 3: Run the checks.** `tox -e lint,static,unit`. Expected: pass. If the env vars are available, run `tox -e integration -- -k profiling`. Expected: PASS. Otherwise, say in the PR description that it wasn't run.
- [ ] **Step 4: Commit and open the PR** (only after the user confirms).

```bash
git add README.md tests/unit/test_repo_baseline.py tests/integration/test_charm.py
git commit -m "docs: document profiling relations; add profiling integration test"
```
