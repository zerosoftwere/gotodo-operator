# gotodo-operator

A Juju machine charm for GoTodo, a small todo app with a JSON API, a web UI, SQLite storage and JWT auth. The charm installs GoTodo from GitHub releases (checksum verified), runs it under systemd as the `gotodo` user, and integrates with alloy-sub for metrics, journal logs and continuous profiling, and with Grafana for dashboards.

## Configuration

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `version` | string | `v0.1.0` | GoTodo release to install. Changing it upgrades or downgrades. |
| `port` | int | `8080` | Public port for the web UI, API and health endpoint. |
| `ops-port` | int | `6060` | Loopback-only port for Prometheus metrics and Go pprof. |
| `token-ttl` | string | `24h` | Lifetime of issued JWT tokens (Go duration). |
| `mutex-profile-fraction` | int | `5` | Go mutex profile sampling fraction (0 disables). |
| `block-profile-rate` | int | `5` | Go block profile rate (0 disables). |

`port` and `ops-port` must be at least 1024 (the service is unprivileged) and `token-ttl` must be a Go duration such as `24h` or `1h30m`. Invalid configuration sets `BlockedStatus("invalid config: <reason>")`. The charm keeps a restart marker at `/etc/gotodo/.restart-pending` so a change that needs a restart is not lost if a hook fails part way; it is cleared once the restart command returns.

## Actions

| Action | Description |
| --- | --- |
| `start` | Start gotodo (restarting instead if a change is pending). Re-enables it at boot. If the configured version is not installed, retries the install first and fails with "gotodo is not installed; see juju debug-log" if that does not work. |
| `stop` | Stop the service and disable it at boot, so it stays stopped across reboots. Fails with "gotodo is not installed; see juju debug-log" on a unit where it was never installed. The unit stays active with the message "stopped by action; run the start action", and the stop is sticky across hooks until `start` or `restart`. |
| `restart` | Restart the service, retrying the install first if the configured version is not installed (same failure message as `start`). |

Each action returns `active-state`, `sub-state` and `main-pid`.

If the configured version is not installed (for example a failed download), `update-status` sets `Blocked("gotodo <version> is not installed; run the restart action to retry")`. It never downloads; run the `restart` action to retry.

## Relations (provides)

| Endpoint | Interface | Purpose |
| --- | --- | --- |
| `machine-observability` | `machine_observability` (container scope) | Publishes the metrics scrape target (`localhost:6060`) and the `gotodo.service` journal source to alloy-sub. |
| `profiling-source` | `pprof_scrape` (container scope) | Publishes pprof targets so alloy-sub can scrape profiles. |
| `grafana-dashboard` | `grafana_dashboard` | Provides the "GoTodo" and "GoTodo profiles" dashboards. |

alloy-sub must always be related to gotodo over `juju-info` (it attaches the subordinate and provides topology). `machine-observability` and `profiling-source` are independent and optional. `send-profiles` goes straight to `pyroscope-vm:profiling`, not through opentelemetry-collector, whose v0.130.0 profile encoding Pyroscope 1.21.0 rejects.

## Target topology

```
juju deploy ./gotodo_*.charm gotodo
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

## Paths

| Path | Owner and mode | Notes |
| --- | --- | --- |
| `/opt/gotodo` | `gotodo:gotodo` 0755 | Binary. |
| `/var/gotodo` | `gotodo:gotodo` 0750 | Data (SQLite). Survives removal of the charm. |
| `/etc/gotodo/gotodo.env` | `root` 0600 | Environment, including the JWT secret. |

The ops port (`ops-port`, default 6060) listens on `127.0.0.1` only; alloy runs on the same machine and scrapes it locally.

## Manual verification runbook

After deploying and relating as above, and generating some traffic:

- Mimir: `gotodo_http_requests_total{juju_application="gotodo"}` returns series.
- Loki: `{juju_application="gotodo"}` returns journal lines.
- Pyroscope: query `service_name=gotodo` shows CPU, heap, mutex and block profiles.
- Grafana: the dashboards "GoTodo" and "GoTodo profiles" are present and populated.

## Development

```
uvx --with tox-uv tox -e format,lint,unit
charmcraft pack
CHARM_PATH=$(ls ./gotodo_*.charm) tox -e integration
```

The integration tests deploy to a VM on a Juju controller. Set `ALLOY_SUB_CHARM_PATH` to also run the alloy-sub scrape test. See [CONTRIBUTING.md](CONTRIBUTING.md).
