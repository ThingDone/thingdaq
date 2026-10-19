"""Read-only, bounded wire negotiation shared by discovery and sessions."""

from __future__ import annotations

from time import monotonic

from ._generated import protocol_constants as c
from .models import CommandResponse, ResponseValue
from .models_v3 import V3Response
from .reader import BackgroundReader, ProtocolVersionRejected, RequestTimeoutError


class InfoNegotiation:
    """Prefer v3; retain historical v1 defaults before trying v2-only releases.

    Only a correlated UNSUPPORTED_VERSION advances the probe order (3, 1, 2).
    Firmware's generic legacy rejection echoes request ID, kind and version;
    no timeout, checksum, malformed-metadata or INVALID_LENGTH exception is
    permitted. Each exchange has one overall deadline and at most three writes.
    Retries retain the current version. No transport is reopened by this policy.
    """

    def __init__(self) -> None:
        self._versions = iter((3, 1, 2))
        self.version = next(self._versions)

    def probe(
        self, reader: BackgroundReader, timeout: float
    ) -> CommandResponse[ResponseValue] | V3Response:
        deadline = monotonic() + timeout
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise RequestTimeoutError(c.FrameKind.INFO_REQUEST, 0, timeout)
            try:
                return reader.request(
                    c.FrameKind.INFO_REQUEST,
                    protocol_version=self.version,
                    timeout=remaining,
                    _negotiating=True,
                )
            except ProtocolVersionRejected:
                version = next(self._versions, None)
                if version is None:
                    raise
                self.version = version
