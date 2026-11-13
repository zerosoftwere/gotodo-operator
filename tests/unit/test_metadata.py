# Copyright 2026 Alhassan Ibrahim
# See LICENSE file for licensing details.

import pathlib

import yaml

CHARMCRAFT = yaml.safe_load(
    (pathlib.Path(__file__).parents[2] / "charmcraft.yaml").read_text(encoding="utf-8")
)


def test_platforms_amd64_only():
    assert list(CHARMCRAFT["platforms"]) == ["ubuntu@24.04:amd64"]
    assert "base" not in CHARMCRAFT
    assert CHARMCRAFT["assumes"] == ["juju >= 3.6"]


def test_provides_interfaces():
    assert "requires" not in CHARMCRAFT
    assert CHARMCRAFT["provides"] == {
        "machine-observability": {
            "interface": "machine_observability",
            "scope": "container",
            "optional": True,
        },
        "profiling-source": {
            "interface": "pprof_scrape",
            "scope": "container",
            "optional": True,
        },
        "grafana-dashboard": {"interface": "grafana_dashboard", "optional": True},
    }


def test_config_defaults():
    options = CHARMCRAFT["config"]["options"]
    expected = {
        "version": ("string", "v0.1.0"),
        "port": ("int", 8080),
        "ops-port": ("int", 6060),
        "token-ttl": ("string", "24h"),
        "mutex-profile-fraction": ("int", 5),
        "block-profile-rate": ("int", 5),
    }
    assert {k: (v["type"], v["default"]) for k, v in options.items()} == expected


def test_actions():
    assert set(CHARMCRAFT["actions"]) == {"start", "stop", "restart"}
    for action in CHARMCRAFT["actions"].values():
        assert "params" not in action
