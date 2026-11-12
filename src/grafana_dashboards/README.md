# Bundled dashboards

Copied from the gotodo repo, `deploy/grafana/` at commit `1d50887`
(`gotodo-dashboard.json`, `gotodo-profiles-dashboard.json`), and adapted for
Juju-managed Grafana. The originals are unchanged. The charm sets each dashboard's `uid`
at load time (`src/dashboards.py`).

## gotodo-dashboard.json (metrics)

- Dropped the `datasource` template variable.
- Every Prometheus datasource reference changed from `${datasource}` to `${prometheusds}`
  (injected by the grafana_dashboard lib / Grafana).
- Replaced the `instance` variable with `juju_unit`, using
  `label_values(gotodo_http_requests_in_flight{juju_application=~"$juju_application"}, juju_unit)`,
  because `instance` is `localhost:<port>` on every unit.
- Every `instance=~"$instance"` matcher changed to `juju_unit=~"$juju_unit"`.
- `job` and `route` variables kept.

## gotodo-profiles-dashboard.json (Pyroscope)

No edits. It keeps its own `datasource` variable (type `grafana-pyroscope-datasource`),
its `instance` variable already uses the label `instance` (set by alloy-sub to the Juju
unit name), and all profile type IDs match those observed in the alloy-sub spike.
