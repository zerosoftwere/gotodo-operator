#!/usr/bin/env python3
# Copyright 2026 Alhassan Ibrahim
# See LICENSE file for licensing details.

"""Charm the GoTodo application."""

import logging
import re

import ops
from charms.dwellir_observability.v0.machine_observability import (
    MachineObservabilityPayload,
    MachineObservabilityProvider,
    MetricsEndpoint,
    SourceTopology,
)

import gotodo

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^v[0-9A-Za-z._+-]+$")
_STOPPED_MSG = "stopped by action; run the start action"
_UNHEALTHY_MSG = "gotodo did not become healthy; see journalctl -u gotodo"


class ConfigError(Exception):
    """Raised when charm configuration is invalid."""


class _LeaderOnlyMachineObservabilityProvider(MachineObservabilityProvider):
    """Provider that only writes app data on the leader and tolerates bad config."""

    def _on_refresh(self, _: ops.EventBase) -> None:
        if not self.model.unit.is_leader() or self._payload_factory is None:
            return
        try:
            payload = self._payload_factory()
        except ConfigError:
            return
        self.publish(payload)

    def publish(self, payload: MachineObservabilityPayload | dict) -> None:
        """Publish the payload, only when this unit is the leader."""
        if not self.model.unit.is_leader():
            return
        super().publish(payload)


class GotodoOperatorCharm(ops.CharmBase):
    """Charm the GoTodo application."""

    _stored = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._stored.set_default(intended_stopped=False)
        self._mo = _LeaderOnlyMachineObservabilityProvider(
            self,
            payload_factory=self._machine_observability_payload,
            refresh_events=[  # pyright: ignore[reportArgumentType]
                self.on.config_changed,
                self.on.upgrade_charm,
                self.on.leader_elected,
            ],
        )
        framework.observe(self.on.install, self._on_reconcile)
        framework.observe(self.on.config_changed, self._on_reconcile)
        framework.observe(self.on.upgrade_charm, self._on_reconcile)
        framework.observe(self.on.start, self._on_reconcile)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.remove, self._on_remove)
        framework.observe(self.on.start_action, self._on_start_action)
        framework.observe(self.on.stop_action, self._on_stop_action)
        framework.observe(self.on.restart_action, self._on_restart_action)

    # Configuration

    def _version(self) -> str:
        version = str(self.config["version"])
        if not _VERSION_RE.fullmatch(version) or ".." in version:
            raise ConfigError(f"version {version!r} must look like v1.2.3")
        return version

    def _settings(self) -> gotodo.Settings:
        """Validate config and return the runtime settings."""
        port = int(self.config["port"])
        ops_port = int(self.config["ops-port"])
        token_ttl = str(self.config["token-ttl"])
        mutex = int(self.config["mutex-profile-fraction"])
        block = int(self.config["block-profile-rate"])
        for name, value in (("port", port), ("ops-port", ops_port)):
            if not 1 <= value <= 65535:
                raise ConfigError(f"{name} must be between 1 and 65535")
        if port == ops_port:
            raise ConfigError("port and ops-port must differ")
        if not token_ttl or any(c.isspace() for c in token_ttl):
            raise ConfigError("token-ttl must be non-empty and contain no whitespace")
        if mutex < 0:
            raise ConfigError("mutex-profile-fraction must be >= 0")
        if block < 0:
            raise ConfigError("block-profile-rate must be >= 0")
        return gotodo.Settings(port, ops_port, token_ttl, mutex, block)

    def _validated(self) -> tuple[str, gotodo.Settings] | None:
        """Return (version, settings), or set Blocked and return None."""
        try:
            return self._version(), self._settings()
        except ConfigError as e:
            self.unit.status = ops.BlockedStatus(f"invalid config: {e}")
            return None

    # State helpers

    def _running(self) -> bool:
        """Return True when installed, not intended stopped, and active."""
        return (
            gotodo.installed_version() is not None
            and not self._stored.intended_stopped
            and gotodo.is_active()
        )

    def _refresh_relations(self) -> None:
        """Refresh relation data; skipped while config is invalid."""
        try:
            payload = self._machine_observability_payload()
        except ConfigError:
            return
        self._mo.publish(payload)

    def _machine_observability_payload(self) -> MachineObservabilityPayload:
        """Build the v3 payload; raises ConfigError on invalid config."""
        ops_port = self._settings().ops_port
        return MachineObservabilityPayload(
            schema_version=3,
            charm_name=self.meta.name,
            source_topology=SourceTopology(
                model=self.model.name,
                model_uuid=self.model.uuid,
                application=self.app.name,
                unit=self.unit.name,
                charm_name=self.meta.name,
            ),
            metrics_endpoints=[
                MetricsEndpoint(targets=[f"localhost:{ops_port}"], path="/metrics", scheme="http")
            ],
            systemd_units=["gotodo.service"],
            journal_match_expressions=[],
            log_files=[],
            artifacts=[],
        )

    # Event handlers

    def _on_reconcile(self, _: ops.EventBase) -> None:
        self._reconcile()

    def _reconcile(self) -> None:
        """Converge the workload on the configured state."""
        validated = self._validated()
        if validated is None:
            return
        version, settings = validated

        gotodo.ensure_user()
        if gotodo.installed_version() != version:
            self.unit.status = ops.MaintenanceStatus(f"installing gotodo {version}")
            try:
                gotodo.install_release(version)
            except gotodo.ChecksumError:
                logger.error("checksum mismatch for gotodo %s", version)
                self.unit.status = ops.BlockedStatus(f"checksum mismatch for gotodo {version}")
                return
            except (gotodo.DownloadError, gotodo.ArchiveError) as e:
                logger.error("installing gotodo %s failed: %s", version, e)
                self.unit.status = ops.BlockedStatus(
                    f"download of gotodo {version} failed; see juju debug-log"
                )
                return
            gotodo.mark_restart_pending()

        gotodo.ensure_dirs()
        secret = gotodo.load_or_create_jwt_secret()
        if gotodo.write_file_if_changed(
            gotodo.ENV_PATH, gotodo.render_env(settings, secret), mode=0o600
        ):
            gotodo.mark_restart_pending()
        if gotodo.write_file_if_changed(gotodo.UNIT_PATH, gotodo.render_unit(), mode=0o644):
            gotodo.mark_restart_pending()
            gotodo.daemon_reload()
            gotodo.enable()

        self.unit.set_ports(settings.port)
        self.unit.set_workload_version(version)

        if self._stored.intended_stopped:
            self.unit.status = ops.ActiveStatus(_STOPPED_MSG)
        elif gotodo.restart_pending() or not gotodo.is_active():
            self.unit.status = ops.MaintenanceStatus("restarting gotodo")
            gotodo.restart()
            gotodo.clear_restart_pending()
            if gotodo.wait_healthy(settings.port):
                self.unit.status = ops.ActiveStatus("")
            else:
                self.unit.status = ops.BlockedStatus(_UNHEALTHY_MSG)
        else:
            self.unit.status = ops.ActiveStatus("")

        self._refresh_relations()

    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Check the workload without restarting it."""
        validated = self._validated()
        if validated is None:
            return
        _version, settings = validated
        if self._stored.intended_stopped:
            self.unit.status = ops.ActiveStatus(_STOPPED_MSG)
        elif not gotodo.is_active():
            self.unit.status = ops.BlockedStatus("gotodo is not running; run the restart action")
        elif not gotodo.wait_healthy(settings.port, timeout=5):
            self.unit.status = ops.BlockedStatus(_UNHEALTHY_MSG)
        else:
            self.unit.status = ops.ActiveStatus("")

    def _action_port(self, event: ops.ActionEvent) -> int | None:
        """Return the validated port, or fail the action and return None."""
        validated = self._validated()
        if validated is None:
            event.fail(str(self.unit.status.message))
            return None
        return validated[1].port

    def _finish_action(self, event: ops.ActionEvent, port: int) -> None:
        """Wait for health, set status and report the service state."""
        if gotodo.wait_healthy(port):
            self.unit.status = ops.ActiveStatus("")
            event.set_results(gotodo.service_state())
        else:
            self.unit.status = ops.BlockedStatus(_UNHEALTHY_MSG)
            event.fail(_UNHEALTHY_MSG)
        self._refresh_relations()

    def _on_start_action(self, event: ops.ActionEvent) -> None:
        port = self._action_port(event)
        if port is None:
            return
        self._stored.intended_stopped = False
        if gotodo.restart_pending():
            gotodo.restart()
        else:
            gotodo.start()
        gotodo.clear_restart_pending()
        self._finish_action(event, port)

    def _on_restart_action(self, event: ops.ActionEvent) -> None:
        port = self._action_port(event)
        if port is None:
            return
        self._stored.intended_stopped = False
        gotodo.restart()
        gotodo.clear_restart_pending()
        self._finish_action(event, port)

    def _on_stop_action(self, event: ops.ActionEvent) -> None:
        self._stored.intended_stopped = True
        gotodo.stop()
        self.unit.status = ops.ActiveStatus(_STOPPED_MSG)
        event.set_results(gotodo.service_state())
        self._refresh_relations()

    def _on_remove(self, _: ops.RemoveEvent) -> None:
        """Remove the service and its files; /var/gotodo is kept."""
        gotodo.remove_service()
        gotodo.clear_restart_pending()


if __name__ == "__main__":  # pragma: nocover
    ops.main(GotodoOperatorCharm)
