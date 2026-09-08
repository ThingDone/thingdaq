"""Independent property tests for the auxiliary-input v2 wire contract."""

from __future__ import annotations

import hashlib
import struct
import unittest
import zlib
from pathlib import Path

from thingdone_daq import (
    ADCBlock,
    AuxBankMode,
    DAQConfiguration,
    FrameValidationError,
    GPIOBlock,
    RateProfile,
    Source,
    StreamMask,
)
from thingdone_daq._generated import protocol_constants as v1_constants
from thingdone_daq._generated import protocol_v2_constants as constants
from thingdone_daq.protocol_v2 import (
    IncrementalCompatibleFrameParser,
    V2ConfigurationEchoError,
    V2FrameValidationError,
    decode_v2_configuration,
    decode_v2_frame,
    encode_v2_frame,
    validate_v2_configuration_echo,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V1_FIXTURE_ROOT = REPOSITORY_ROOT / "protocol/fixtures"
V2_FIXTURE_ROOT = REPOSITORY_ROOT / "protocol/fixtures-v2"

_CONFIGURE_REQUEST = struct.Struct("<BBBBIII")
_CONFIGURE_RESPONSE = struct.Struct("<BBHBBBBIII")
_TRAILER = struct.Struct("<I")
_FROZEN_V1_TREE_SHA256 = (
    "f7b4720576ae6b163f70f279a8517d57f7fed9100fd48cefb4fbc9d03a0958b1"
)


def _reference_checksum(data: bytes, algorithm: int) -> int:
    if algorithm == int(constants.ChecksumAlgorithm.ADLER32):
        return zlib.adler32(data) & 0xFFFF_FFFF
    if algorithm == int(constants.ChecksumAlgorithm.CRC32_ISO_HDLC):
        return zlib.crc32(data) & 0xFFFF_FFFF
    if algorithm == int(constants.ChecksumAlgorithm.CRC32C):
        remainder = 0xFFFF_FFFF
        for value in data:
            remainder ^= value
            for _ in range(8):
                remainder = (remainder >> 1) ^ (0x82F6_3B78 if remainder & 1 else 0)
        return remainder ^ 0xFFFF_FFFF
    raise AssertionError(f"test oracle does not implement checksum {algorithm}")


def _replace_payload(wire: bytes, payload: bytes) -> bytes:
    if len(payload) != len(wire) - constants.HEADER_SIZE - constants.TRAILER_SIZE:
        raise AssertionError("test mutation must preserve the declared frame shape")
    body = wire[: constants.HEADER_SIZE] + payload
    algorithm = wire[constants.HEADER_CHECKSUM_ALGORITHM_OFFSET]
    return body + _TRAILER.pack(_reference_checksum(body, algorithm))


def _mutate_payload_scalar(
    wire: bytes,
    offset: int,
    field_format: str,
    value: int,
) -> bytes:
    payload = bytearray(wire[constants.HEADER_SIZE : -constants.TRAILER_SIZE])
    struct.pack_into("<" + field_format, payload, offset, value)
    return _replace_payload(wire, bytes(payload))


def _configuration_payload(
    mode: AuxBankMode,
    profile: RateProfile,
    *,
    streams: StreamMask = StreamMask.ADC | StreamMask.GPIO,
    source: Source = Source.SYNTHETIC,
    checksum: v1_constants.ChecksumAlgorithm = v1_constants.ChecksumAlgorithm.CRC32C,
) -> bytes:
    timing = constants.RATE_PROFILE_TIMING[profile]
    return _CONFIGURE_REQUEST.pack(
        int(streams),
        int(source),
        int(checksum),
        int(mode),
        constants.DATA_FRAME_BYTES,
        timing["adc_pair_rate_hz"],
        timing["gpio_sample_rate_hz"],
    )


def _successful_echo(request_payload: bytes) -> bytes:
    return _CONFIGURE_RESPONSE.pack(
        0, 0, 0, *_CONFIGURE_REQUEST.unpack(request_payload)
    )


class GeneratedConfigurationPropertyTests(unittest.TestCase):
    def test_every_public_valid_mode_profile_configuration_round_trips(self) -> None:
        observed = 0
        checksums = (
            v1_constants.ChecksumAlgorithm.ADLER32,
            v1_constants.ChecksumAlgorithm.CRC32C,
            v1_constants.ChecksumAlgorithm.CRC32_ISO_HDLC,
        )
        for mode in AuxBankMode:
            stream_masks = (
                (StreamMask.ADC, StreamMask.GPIO, StreamMask.ADC | StreamMask.GPIO)
                if mode is AuxBankMode.DISABLED
                else (StreamMask.GPIO, StreamMask.ADC | StreamMask.GPIO)
            )
            for profile in RateProfile:
                timing = constants.RATE_PROFILE_TIMING[profile]
                for streams in stream_masks:
                    for source in Source:
                        for checksum in checksums:
                            with self.subTest(
                                mode=mode.name,
                                profile=profile.name,
                                streams=int(streams),
                                source=source.name,
                                checksum=checksum.name,
                            ):
                                configuration = DAQConfiguration(
                                    stream_mask=streams,
                                    source=source,
                                    data_checksum_algorithm=checksum,
                                    aux_bank_mode=mode,
                                    rate_profile=profile,
                                )
                                payload = configuration.to_payload(
                                    protocol_version=constants.PROTOCOL_VERSION
                                )
                                fields = decode_v2_configuration(payload)
                                echoed = validate_v2_configuration_echo(
                                    payload,
                                    _successful_echo(payload),
                                )
                                self.assertEqual(fields, echoed)
                                self.assertEqual(mode, fields.aux_bank_mode)
                                self.assertEqual(profile, fields.rate_profile)
                                self.assertEqual(
                                    timing["adc_pair_rate_hz"],
                                    fields.adc_pair_rate_hz,
                                )
                                self.assertEqual(
                                    timing["gpio_sample_rate_hz"],
                                    fields.gpio_sample_rate_hz,
                                )
                                self.assertEqual(
                                    configuration,
                                    DAQConfiguration.from_payload(payload),
                                )
                                observed += 1
        self.assertEqual(150, observed)

    def test_all_undeclared_auxiliary_mode_bytes_fail_closed(self) -> None:
        valid = 0
        rejected = 0
        for raw_mode in range(256):
            payload = bytearray(
                _configuration_payload(
                    AuxBankMode.DISABLED,
                    RateProfile.ADC_1MHZ_GPIO_4MHZ,
                )
            )
            payload[constants.CONFIGURE_REQUEST_AUX_BANK_MODE_OFFSET] = raw_mode
            if raw_mode in {int(mode) for mode in AuxBankMode}:
                fields = decode_v2_configuration(payload)
                self.assertEqual(raw_mode, int(fields.aux_bank_mode))
                valid += 1
                continue
            with self.subTest(raw_mode=raw_mode):
                with self.assertRaises(V2FrameValidationError) as raised:
                    decode_v2_configuration(payload)
                self.assertEqual("invalid_aux_bank_mode", raised.exception.reason)
                with self.assertRaises(FrameValidationError):
                    DAQConfiguration.from_payload(payload)
                rejected += 1
        self.assertEqual((2, 254), (valid, rejected))

    def test_every_declared_rate_and_rejection_class_is_categorized(self) -> None:
        for profile in RateProfile:
            payload = _configuration_payload(AuxBankMode.INPUT, profile)
            fields = decode_v2_configuration(payload)
            with self.subTest(profile=profile.name):
                self.assertEqual(profile, fields.rate_profile)

        cases = (
            (0, 0, "nonintegral_timestamps"),
            (3, 12, "nonintegral_timestamps"),
            (1_000_000, 2_000_000, "wrong_four_to_one_ratio"),
            (200_000, 800_000, "unsupported_rates"),
            (100_000, 400_000, "unsupported_rates"),
            (1_000_000, 4_000_001, "nonintegral_timestamps"),
        )
        for adc_rate, gpio_rate, reason in cases:
            payload = _CONFIGURE_REQUEST.pack(
                int(StreamMask.ADC | StreamMask.GPIO),
                int(Source.SYNTHETIC),
                int(v1_constants.ChecksumAlgorithm.CRC32C),
                int(AuxBankMode.INPUT),
                constants.DATA_FRAME_BYTES,
                adc_rate,
                gpio_rate,
            )
            with self.subTest(adc_rate=adc_rate, gpio_rate=gpio_rate):
                with self.assertRaises(V2FrameValidationError) as raised:
                    decode_v2_configuration(payload)
                self.assertEqual(reason, raised.exception.reason)

    def test_each_valid_applied_field_group_mismatch_is_rejected(self) -> None:
        requested = _configuration_payload(
            AuxBankMode.INPUT,
            RateProfile.ADC_250KHZ_GPIO_1MHZ,
        )
        alternatives = {
            "streams": _configuration_payload(
                AuxBankMode.INPUT,
                RateProfile.ADC_250KHZ_GPIO_1MHZ,
                streams=StreamMask.GPIO,
            ),
            "source": _configuration_payload(
                AuxBankMode.INPUT,
                RateProfile.ADC_250KHZ_GPIO_1MHZ,
                source=Source.HARDWARE,
            ),
            "checksum": _configuration_payload(
                AuxBankMode.INPUT,
                RateProfile.ADC_250KHZ_GPIO_1MHZ,
                checksum=v1_constants.ChecksumAlgorithm.ADLER32,
            ),
            "mode": _configuration_payload(
                AuxBankMode.DISABLED,
                RateProfile.ADC_250KHZ_GPIO_1MHZ,
            ),
            "rate_profile": _configuration_payload(
                AuxBankMode.INPUT,
                RateProfile.ADC_125KHZ_GPIO_500KHZ,
            ),
        }
        for field, applied in alternatives.items():
            with self.subTest(field=field):
                with self.assertRaises(V2ConfigurationEchoError) as raised:
                    validate_v2_configuration_echo(
                        requested,
                        _successful_echo(applied),
                    )
                self.assertEqual(
                    "contradictory_configure_echo",
                    raised.exception.reason,
                )

        invalid_frame_size = bytearray(_successful_echo(requested))
        struct.pack_into(
            "<I",
            invalid_frame_size,
            constants.CONFIGURE_RESPONSE_DATA_FRAME_BYTES_OFFSET,
            constants.DATA_FRAME_BYTES - 1,
        )
        with self.assertRaises(V2FrameValidationError):
            validate_v2_configuration_echo(requested, invalid_frame_size)


class GeneratedLayoutMutationTests(unittest.TestCase):
    def test_all_mode_profile_wire_shapes_decode_only_as_negotiated(self) -> None:
        for mode in AuxBankMode:
            layout = constants.AUX_BANK_LAYOUTS[mode]
            for profile in RateProfile:
                timing = constants.RATE_PROFILE_TIMING[profile]
                configuration = DAQConfiguration(
                    stream_mask=StreamMask.ADC | StreamMask.GPIO,
                    source=Source.SYNTHETIC,
                    aux_bank_mode=mode,
                    rate_profile=profile,
                )
                first_ticks = timing[
                    "disabled_frame_coverage_ticks"
                    if mode is AuxBankMode.DISABLED
                    else "input_frame_coverage_ticks"
                ]
                gpio_payload = (
                    bytes(index & 0xFF for index in range(4_048))
                    if mode is AuxBankMode.DISABLED
                    else b"".join(
                        struct.pack("<H", index & 0xFFFF) for index in range(2_024)
                    )
                )
                gpio_wire = encode_v2_frame(
                    constants.FrameKind.GPIO_DATA,
                    gpio_payload,
                    flags=constants.FrameFlag.SYNTHETIC,
                    run_id=7,
                    sequence=1,
                    first_sample_ticks=first_ticks,
                    item_count=layout["gpio_items_per_frame"],
                )
                adc_payload = bytes(layout["adc_payload_bytes"])
                adc_wire = encode_v2_frame(
                    constants.FrameKind.ADC_DATA,
                    adc_payload,
                    flags=constants.FrameFlag.SYNTHETIC,
                    run_id=7,
                    sequence=1,
                    first_sample_ticks=first_ticks,
                    item_count=layout["adc_items_per_frame"],
                )
                with self.subTest(mode=mode.name, profile=profile.name):
                    gpio = GPIOBlock.from_v2_frame(
                        decode_v2_frame(gpio_wire), configuration
                    )
                    adc = ADCBlock.from_v2_frame(
                        decode_v2_frame(adc_wire), configuration
                    )
                    self.assertEqual(layout["gpio_items_per_frame"], gpio.item_count)
                    self.assertEqual(layout["adc_items_per_frame"], adc.item_count)
                    self.assertEqual(first_ticks, gpio.first_sample_ticks)
                    self.assertEqual(first_ticks, adc.first_sample_ticks)
                    if mode is AuxBankMode.INPUT:
                        self.assertEqual(0x0100, gpio.sample(256))
                        self.assertEqual(b"\x00\x01", gpio.payload[512:514])

                other_mode = (
                    AuxBankMode.INPUT
                    if mode is AuxBankMode.DISABLED
                    else AuxBankMode.DISABLED
                )
                other_configuration = DAQConfiguration(
                    stream_mask=StreamMask.ADC | StreamMask.GPIO,
                    source=Source.SYNTHETIC,
                    aux_bank_mode=other_mode,
                    rate_profile=profile,
                )
                for frame_type, wire in (
                    (GPIOBlock, gpio_wire),
                    (ADCBlock, adc_wire),
                ):
                    with (
                        self.subTest(
                            mode=mode.name,
                            profile=profile.name,
                            wrong_mode=other_mode.name,
                            frame=frame_type.__name__,
                        ),
                        self.assertRaises(FrameValidationError),
                    ):
                        frame_type.from_v2_frame(
                            decode_v2_frame(wire), other_configuration
                        )

    def test_active_info_layout_fields_reject_every_single_field_mutation(self) -> None:
        scalar_fields = (
            (constants.INFO_RESPONSE_SELECTED_RATE_PROFILE_OFFSET, "B"),
            (constants.INFO_RESPONSE_APPLIED_AUX_BANK_MODE_OFFSET, "B"),
            (constants.INFO_RESPONSE_GPIO_PACKED_WIDTH_BITS_OFFSET, "B"),
            (constants.INFO_RESPONSE_GPIO_ITEM_BYTES_OFFSET, "B"),
            (constants.INFO_RESPONSE_GPIO_PIN_COUNT_OFFSET, "B"),
            (constants.INFO_RESPONSE_AUX_GPIO_PIN_COUNT_OFFSET, "B"),
            (constants.INFO_RESPONSE_ADC_PAIR_RATE_HZ_OFFSET, "I"),
            (constants.INFO_RESPONSE_GPIO_SAMPLE_RATE_HZ_OFFSET, "I"),
            (constants.INFO_RESPONSE_ADC_PAIR_PERIOD_TICKS_OFFSET, "H"),
            (constants.INFO_RESPONSE_ADC1_PHASE_TICKS_OFFSET, "H"),
            (constants.INFO_RESPONSE_GPIO_SAMPLE_PERIOD_TICKS_OFFSET, "H"),
            (constants.INFO_RESPONSE_DATA_PAYLOAD_BYTES_OFFSET, "H"),
            (constants.INFO_RESPONSE_ADC_PAIRS_PER_FRAME_OFFSET, "H"),
            (constants.INFO_RESPONSE_GPIO_SAMPLES_PER_FRAME_OFFSET, "H"),
            (constants.INFO_RESPONSE_FRAME_COVERAGE_TICKS_OFFSET, "I"),
            (constants.INFO_RESPONSE_DISABLED_ADC_PAIRS_PER_FRAME_OFFSET, "H"),
            (constants.INFO_RESPONSE_DISABLED_GPIO_SAMPLES_PER_FRAME_OFFSET, "H"),
            (constants.INFO_RESPONSE_INPUT_ADC_PAIRS_PER_FRAME_OFFSET, "H"),
            (constants.INFO_RESPONSE_INPUT_GPIO_SAMPLES_PER_FRAME_OFFSET, "H"),
        )
        for mode_name in ("disabled", "input"):
            for profile_name in (
                "adc-1mhz-gpio-4mhz",
                "adc-500khz-gpio-2mhz",
                "adc-250khz-gpio-1mhz",
                "adc-125khz-gpio-500khz",
            ):
                wire = (
                    V2_FIXTURE_ROOT / f"info-{mode_name}-{profile_name}-response.bin"
                ).read_bytes()
                decode_v2_frame(wire)
                payload = wire[constants.HEADER_SIZE : -constants.TRAILER_SIZE]
                for offset, field_format in scalar_fields:
                    current = struct.unpack_from("<" + field_format, payload, offset)[0]
                    width_mask = (1 << (8 * struct.calcsize(field_format))) - 1
                    changed = (int(current) + 1) & width_mask
                    with self.subTest(
                        mode=mode_name,
                        profile=profile_name,
                        offset=offset,
                    ):
                        mutated = _mutate_payload_scalar(
                            wire,
                            offset,
                            field_format,
                            changed,
                        )
                        with self.assertRaises(V2FrameValidationError):
                            decode_v2_frame(mutated)

                for map_offset, count in (
                    (
                        constants.INFO_RESPONSE_GPIO_PIN_MAP_OFFSET,
                        constants.INFO_RESPONSE_GPIO_PIN_MAP_COUNT,
                    ),
                    (
                        constants.INFO_RESPONSE_AUX_GPIO_PIN_MAP_OFFSET,
                        constants.INFO_RESPONSE_AUX_GPIO_PIN_MAP_COUNT,
                    ),
                    (
                        constants.INFO_RESPONSE_AUX_GPIO_PORT_BITS_OFFSET,
                        constants.INFO_RESPONSE_AUX_GPIO_PORT_BITS_COUNT,
                    ),
                ):
                    for relative in range(count):
                        offset = map_offset + relative
                        with self.subTest(
                            mode=mode_name,
                            profile=profile_name,
                            map_offset=map_offset,
                            relative=relative,
                        ):
                            mutated = _mutate_payload_scalar(
                                wire,
                                offset,
                                "B",
                                payload[offset] ^ 0x01,
                            )
                            with self.assertRaises(V2FrameValidationError):
                                decode_v2_frame(mutated)


class CompatibilityAndFragmentationPropertyTests(unittest.TestCase):
    def test_complete_v1_contract_tree_is_byte_frozen(self) -> None:
        paths = [
            REPOSITORY_ROOT / "protocol/protocol-v1.json",
            REPOSITORY_ROOT
            / "daq_api/src/thingdone_daq/_generated/protocol_constants.py",
            REPOSITORY_ROOT / "firmware/src/generated/protocol_constants.h",
            *sorted(V1_FIXTURE_ROOT.glob("*")),
        ]
        digest = hashlib.sha256()
        file_count = 0
        for path in paths:
            if not path.is_file():
                continue
            # The frozen digest includes historical filenames. Relocate only
            # the Python namespace; continue checking every original byte.
            relative = (
                path.relative_to(REPOSITORY_ROOT)
                .as_posix()
                .replace("src/thingdone_daq/", "src/thingdaq/")
                .encode()
            )
            contents = path.read_bytes()
            digest.update(len(relative).to_bytes(4, "little"))
            digest.update(relative)
            digest.update(len(contents).to_bytes(8, "little"))
            digest.update(contents)
            file_count += 1
        self.assertEqual(27, file_count)
        self.assertEqual(_FROZEN_V1_TREE_SHA256, digest.hexdigest())

    def test_compatible_parser_survives_every_split_across_both_layouts(self) -> None:
        expected = (
            (V1_FIXTURE_ROOT / "ping-request.bin").read_bytes(),
            (V2_FIXTURE_ROOT / "gpio-8bit-adc-500khz-gpio-2mhz.bin").read_bytes(),
            (V2_FIXTURE_ROOT / "adc-data.bin").read_bytes(),
            (V2_FIXTURE_ROOT / "gpio-16bit-adc-125khz-gpio-500khz.bin").read_bytes(),
        )
        stream = b"".join(expected)
        for split in range(len(stream) + 1):
            parser = IncrementalCompatibleFrameParser()
            decoded = parser.feed(stream[:split])
            decoded.extend(parser.feed(stream[split:]))
            if tuple(frame.to_bytes() for frame in decoded) != expected:
                self.fail(f"compatible parser failed at split offset {split}")
            self.assertLessEqual(parser.high_water_mark, parser.max_buffered_bytes)
            self.assertEqual(0, parser.buffered_bytes)
            self.assertEqual(0, parser.corruption_events)

    def test_byte_fragmentation_covers_every_mode_profile_gpio_frame(self) -> None:
        parser = IncrementalCompatibleFrameParser()
        expected: list[bytes] = []
        for width in (8, 16):
            for profile_name in (
                "adc-1mhz-gpio-4mhz",
                "adc-500khz-gpio-2mhz",
                "adc-250khz-gpio-1mhz",
                "adc-125khz-gpio-500khz",
            ):
                expected.append(
                    (
                        V2_FIXTURE_ROOT / f"gpio-{width}bit-{profile_name}.bin"
                    ).read_bytes()
                )
        decoded = []
        for frame in expected:
            for value in frame:
                decoded.extend(parser.feed(bytes((value,))))
                self.assertLessEqual(
                    parser.buffered_bytes,
                    parser.max_buffered_bytes,
                )
        self.assertEqual(expected, [frame.to_bytes() for frame in decoded])
        self.assertEqual(0, parser.buffered_bytes)
        self.assertEqual(0, parser.corruption_events)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
