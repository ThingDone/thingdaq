"""Capability-first CONFIGURE validation and exact echo checks."""

from __future__ import annotations

import unittest

from thingdone_daq import (
    ChecksumAlgorithm,
    DAQConfiguration,
    DeviceCapabilityError,
    FrameKind,
    InMemoryTransport,
    SimulatedDevice,
    Source,
    StreamMask,
    ThingDAQ,
    UnexpectedMessageError,
    decode_frame,
)


class CountingTransport(InMemoryTransport):
    """Count complete CONFIGURE requests written to the simulated peer."""

    def __init__(self, device: SimulatedDevice | None = None) -> None:
        super().__init__(device)
        self.configure_requests = 0

    def write(self, data: bytes | bytearray | memoryview) -> int:
        frame = decode_frame(bytes(data))
        if frame.header.kind is FrameKind.CONFIGURE_REQUEST:
            self.configure_requests += 1
        return super().write(data)


class RewritingConfigureDevice(SimulatedDevice):
    """Apply a valid request but echo a different successful configuration."""

    def _handle_configure(self, request):  # type: ignore[no-untyped-def]
        super()._handle_configure(request)
        changed = DAQConfiguration(
            stream_mask=StreamMask.GPIO,
            source=Source.SYNTHETIC,
            data_checksum_algorithm=ChecksumAlgorithm.ADLER32,
        )
        return self._success_response(request, bytes(4) + changed.to_payload())


class RewritingStartDevice(SimulatedDevice):
    """Start successfully but echo a profile other than CONFIGURE selected."""

    def _handle_start(self, request):  # type: ignore[no-untyped-def]
        super()._handle_start(request)
        changed = DAQConfiguration(
            stream_mask=StreamMask.GPIO,
            source=Source.SYNTHETIC,
            data_checksum_algorithm=ChecksumAlgorithm.ADLER32,
        )
        return self._success_response(
            request,
            bytes(4) + changed.to_payload(),
            run_id=self.run_id,
        )


class CapabilityDrivenConfigurationTests(unittest.TestCase):
    def test_exact_rate_and_resolution_requirements_are_sent_and_echoed(self) -> None:
        transport = CountingTransport()
        with ThingDAQ.open(transport) as daq:
            applied = daq.configure(
                adc=True,
                gpio=True,
                source=Source.SYNTHETIC,
                checksum_algorithm=ChecksumAlgorithm.CRC32C,
                adc_pair_rate_hz=1_000_000,
                gpio_sample_rate_hz=4_000_000,
                adc_resolution_bits=12,
            )

        self.assertEqual(1, transport.configure_requests)
        self.assertEqual(StreamMask.ADC | StreamMask.GPIO, applied.stream_mask)
        self.assertEqual(Source.SYNTHETIC, applied.source)
        self.assertEqual(ChecksumAlgorithm.CRC32C, applied.data_checksum_algorithm)

    def test_unsupported_requirements_fail_before_configure_is_written(self) -> None:
        transport = CountingTransport()
        with ThingDAQ.open(transport) as daq:
            cases = (
                ({"adc_pair_rate_hz": 999_999}, "ADC pair rate"),
                ({"gpio_sample_rate_hz": 3_999_999}, "GPIO sample rate"),
                ({"adc_resolution_bits": 10}, "ADC resolution"),
            )
            for keywords, message in cases:
                with (
                    self.subTest(keywords=keywords),
                    self.assertRaisesRegex(
                        DeviceCapabilityError,
                        message,
                    ),
                ):
                    daq.configure(source=Source.SYNTHETIC, **keywords)

            with self.assertRaisesRegex(
                DeviceCapabilityError,
                "requested source HARDWARE",
            ):
                daq.configure(source=Source.HARDWARE)

            with self.assertRaisesRegex(ValueError, "need an ADC stream"):
                daq.configure(
                    adc=False,
                    gpio=True,
                    source=Source.SYNTHETIC,
                    adc_resolution_bits=12,
                )

        self.assertEqual(0, transport.configure_requests)

    def test_configure_and_start_reject_changed_applied_echoes(self) -> None:
        with (
            ThingDAQ.open(InMemoryTransport(RewritingConfigureDevice())) as daq,
            self.assertRaisesRegex(
                UnexpectedMessageError,
                "CONFIGURE applied configuration differs",
            ),
        ):
            daq.configure(
                adc=True,
                gpio=False,
                source=Source.SYNTHETIC,
            )

        with ThingDAQ.open(InMemoryTransport(RewritingStartDevice())) as daq:
            daq.configure(
                adc=True,
                gpio=False,
                source=Source.SYNTHETIC,
            )
            with self.assertRaisesRegex(
                UnexpectedMessageError,
                "START applied configuration differs",
            ):
                daq.start()


if __name__ == "__main__":
    unittest.main()
