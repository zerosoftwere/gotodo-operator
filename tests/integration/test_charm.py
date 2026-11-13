# Copyright 2026 Alhassan Ibrahim
# See LICENSE file for licensing details.

"""Integration tests for the gotodo charm.

The tests run in order and share one model: the first test deploys the charm.
Set ``ALLOY_SUB_CHARM_PATH`` to also run the alloy-sub scrape test.
"""

import logging
import os
import pathlib

import jubilant
import pytest

logger = logging.getLogger(__name__)

APP = "gotodo"
UNIT = "gotodo/0"
STOPPED_MSG = "stopped by action; run the start action"


def _unit_message(juju: jubilant.Juju) -> str:
    status = juju.status()
    return status.apps[APP].units[UNIT].workload_status.message


def test_deploy_active(charm: pathlib.Path, juju: jubilant.Juju):
    """The charm deploys on a VM and reaches active status."""
    juju.deploy(
        charm.resolve(),
        app=APP,
        base="ubuntu@24.04",
        constraints={"virt-type": "virtual-machine"},
    )
    juju.wait(jubilant.all_active, timeout=900)


def test_health_endpoint(juju: jubilant.Juju):
    """The public health endpoint answers on the configured port."""
    task = juju.exec("curl -fsS http://127.0.0.1:8080/api/health", unit=UNIT)
    logger.info("health: %s", task.stdout)
    assert task.return_code == 0


def test_files_and_owner(juju: jubilant.Juju):
    """The install, data and env paths have the expected owner and mode."""
    task = juju.exec(
        "stat -c '%n %U %a' /opt/gotodo /var/gotodo /etc/gotodo/gotodo.env", unit=UNIT
    )
    lines = {
        parts[0]: " ".join(parts[1:])
        for parts in (line.split() for line in task.stdout.splitlines())
        if parts
    }
    assert lines["/opt/gotodo"] == "gotodo 755"
    assert lines["/var/gotodo"] == "gotodo 750"
    assert lines["/etc/gotodo/gotodo.env"] == "root 600"


def test_ops_port_is_loopback_only(juju: jubilant.Juju):
    """The ops port listens on 127.0.0.1 only."""
    task = juju.exec("ss -ltn", unit=UNIT)
    listeners = task.stdout
    assert "127.0.0.1:6060" in listeners
    assert "0.0.0.0:6060" not in listeners
    assert "*:6060" not in listeners
    assert "[::]:6060" not in listeners


def test_stop_start_restart_actions(juju: jubilant.Juju):
    """Stop keeps the unit active with a message; start and restart recover it."""
    juju.run(UNIT, "stop")
    juju.wait(lambda status: jubilant.all_active(status, APP), timeout=300)
    assert _unit_message(juju) == STOPPED_MSG

    juju.run(UNIT, "start")
    juju.wait(jubilant.all_active, timeout=300)
    assert _unit_message(juju) == ""

    juju.run(UNIT, "restart")
    juju.wait(jubilant.all_active, timeout=300)
    assert _unit_message(juju) == ""


@pytest.mark.skipif(
    not os.environ.get("ALLOY_SUB_CHARM_PATH"), reason="ALLOY_SUB_CHARM_PATH is not set"
)
def test_alloy_sub_scrapes_metrics_and_journal(juju: jubilant.Juju):
    """alloy-sub, related to gotodo, is configured to scrape metrics and the journal."""
    alloy_charm = pathlib.Path(os.environ["ALLOY_SUB_CHARM_PATH"]).resolve()
    assert alloy_charm.is_file(), f"{alloy_charm} is not a file"
    juju.deploy(alloy_charm, app="alloy-sub", base="ubuntu@24.04")
    juju.integrate("alloy-sub:juju-info", APP)
    juju.integrate(f"{APP}:machine-observability", "alloy-sub:machine-observability")
    juju.wait(lambda status: jubilant.all_agents_idle(status, APP), timeout=900)

    task = juju.exec("cat /etc/alloy/config.alloy", unit=UNIT)
    assert "localhost:6060" in task.stdout
    assert "gotodo.service" in task.stdout
