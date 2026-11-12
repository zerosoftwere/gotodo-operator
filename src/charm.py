#!/usr/bin/env python3
# Copyright 2026 Alhassan Ibrahim
# See LICENSE file for licensing details.

"""Charm the GoTodo application."""

import logging

import ops

logger = logging.getLogger(__name__)


class GotodoOperatorCharm(ops.CharmBase):
    """Charm the GoTodo application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)

    def _on_install(self, event: ops.InstallEvent):
        """Handle install event."""
        self.unit.status = ops.ActiveStatus("")


if __name__ == "__main__":  # pragma: nocover
    ops.main(GotodoOperatorCharm)
