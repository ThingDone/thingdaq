"""Public-v3 control state carried by the existing ThingDAQ/BackgroundReader."""

from __future__ import annotations

from time import monotonic, sleep

from ._generated import protocol_v3_constants as c
from .models_v3 import (
    V3AppliedSettings,
    V3Capabilities,
    V3Info,
    V3Response,
    V3Settings,
    V3Status,
    V3Stop,
)
from .reader import BackgroundReader


class V3Session:
    """Control-only adapter; transport, parsing, queues and loss stay shared."""

    def __init__(self, reader: BackgroundReader, timeout: float) -> None:
        self.reader = reader
        self.timeout = timeout
        self.capabilities: V3Capabilities | None = None
        self.applied: V3AppliedSettings | None = None
        self.identity: V3Info | None = None
        self.state = c.DeviceState.STOPPED
        self.run_id = 0
        self.last_status: V3Status | None = None

    def command(
        self, kind: c.CommandKind, payload: bytes = b"", *, timeout: float | None = None
    ) -> V3Response:
        # Imported here to keep the control adapter independent of facade setup.
        from .client import CommandTimeoutError, DeviceCommandError
        from .reader import RequestTimeoutError

        try:
            response = self.reader.request(
                kind,
                payload,
                protocol_version=3,
                timeout=self.timeout if timeout is None else timeout,
            )
        except RequestTimeoutError as exc:
            raise CommandTimeoutError(exc) from exc
        if not response.ok:
            raise DeviceCommandError(
                c.FrameKind(kind), response.error_code, response.request_id
            )
        if response.kind != c.COMMAND_RESPONSE_KINDS[kind]:
            raise ValueError("v3 response kind differs from command")
        return response

    def info(self) -> V3Info:
        from .client import DeviceIdentityMismatchError

        value = self.command(c.CommandKind.INFO).value
        assert isinstance(value, V3Info)
        if self.identity is not None and (
            value.board_id,
            value.mcu_id,
            value.simulated,
            value.hardware_serial,
            value.firmware_version,
            value.build_id,
        ) != (
            self.identity.board_id,
            self.identity.mcu_id,
            self.identity.simulated,
            self.identity.hardware_serial,
            self.identity.firmware_version,
            self.identity.build_id,
        ):
            raise DeviceIdentityMismatchError("v3 identity changed during session")
        self.identity = value
        return value

    def get_capabilities(self) -> V3Capabilities:
        value = self.command(c.CommandKind.GET_CAPABILITIES).value
        assert isinstance(value, V3Capabilities)
        self.capabilities = value
        return value

    def get_settings(self) -> V3AppliedSettings:
        from .client import UnexpectedMessageError

        value = self.command(c.CommandKind.GET_SETTINGS).value
        assert isinstance(value, V3AppliedSettings)
        # Initial synchronization has just read two INFO records. Reuse that
        # snapshot to keep the bounded open exchange unchanged.
        self._validate_applied(value, refresh_info=self.applied is not None)
        if self.state != c.DeviceState.STOPPED and self.applied != value:
            raise UnexpectedMessageError("v3 settings changed during run/drain")
        self.applied = value
        return value

    def _validate_applied(
        self, value: V3AppliedSettings, *, refresh_info: bool = True
    ) -> None:
        from .client import UnexpectedMessageError

        assert self.capabilities is not None
        self.capabilities.require_supported(value.settings)
        clocks = next(
            record
            for record in self.capabilities.cpu_profiles
            if record.cpu_profile == value.settings.cpu_profile
        )
        if value.clocks != clocks:
            raise UnexpectedMessageError(
                "applied clocks differ from advertised profile"
            )
        info = self.info() if refresh_info else self.identity
        if info is None or info.clocks != value.clocks:
            raise UnexpectedMessageError("INFO clocks differ from applied settings")

    def configure(self, settings: V3Settings) -> V3AppliedSettings:
        from .client import UnexpectedMessageError

        assert self.capabilities is not None
        self.capabilities.require_supported(settings)
        response = self.command(c.CommandKind.CONFIGURE, settings.to_bytes())
        value = response.value
        if not isinstance(value, V3AppliedSettings) or value.settings != settings:
            raise UnexpectedMessageError(
                "CONFIGURE applied settings differ from request"
            )
        readback = self.command(c.CommandKind.GET_SETTINGS).value
        if value != readback:
            raise UnexpectedMessageError("GET_SETTINGS differs from CONFIGURE echo")
        self._validate_applied(value)
        self.applied = value
        self.run_id = response.run_id
        return value

    def start(self) -> int:
        from .client import UnexpectedMessageError

        requested = self.applied
        if self.get_settings() != requested:
            raise UnexpectedMessageError("settings changed before START")
        response = self.command(c.CommandKind.START)
        # Record RUNNING even for a contradictory echo so close still sends STOP.
        self.state = c.DeviceState.RUNNING
        self.run_id = response.run_id
        self.last_status = None
        if not response.run_id or response.value != requested:
            raise UnexpectedMessageError("START run ID/settings differ from request")
        return response.run_id

    def status(self, *, timeout: float | None = None) -> V3Status:
        value = self.command(c.CommandKind.GET_STATUS, timeout=timeout).value
        assert isinstance(value, V3Status)
        self.state = value.state
        self.run_id = value.run_id
        self.last_status = value
        return value

    def stop(self) -> c.DeviceState:
        from .client import UnexpectedMessageError

        deadline = monotonic() + self.timeout
        value = self.command(c.CommandKind.STOP).value
        assert isinstance(value, V3Stop)
        self.state, self.run_id = value.state, value.run_id
        while self.state == c.DeviceState.DRAINING:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise UnexpectedMessageError("v3 STOP drain deadline exceeded")
            sleep(min(0.001, remaining))
            self.status(timeout=max(0.000001, deadline - monotonic()))
        if self.state != c.DeviceState.STOPPED:
            raise UnexpectedMessageError("v3 STOP did not reach STOPPED")
        return self.state
