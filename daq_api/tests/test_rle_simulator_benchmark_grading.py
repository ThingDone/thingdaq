"""Independent simulator equality and deterministic RLE benchmark grading tests."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from thingdaq import (
    ADCBlock,
    ConfigurationEncoding,
    ExperimentalSourcePattern,
    FrameEncoding,
    GPIOBlock,
    ThingDAQ,
    V2Frame,
    count_rle_runs,
)
from thingdaq import rle_benchmark as benchmark
from thingdaq._generated import protocol_v2_constants as constants
from thingdaq.simulator import experimental_adc_payload, experimental_gpio_payload


class ExperimentalSimulatorFormulaTests(unittest.TestCase):
    def test_two_frame_raw_and_rle_runs_match_every_exact_source_formula(
        self,
    ) -> None:
        for pattern in ExperimentalSourcePattern:
            captures: dict[
                ConfigurationEncoding,
                tuple[ADCBlock | GPIOBlock, ...],
            ] = {}
            framed_bytes: dict[ConfigurationEncoding, int] = {}
            for encoding in (
                ConfigurationEncoding.RAW,
                ConfigurationEncoding.RLE_AUTO,
            ):
                with ThingDAQ.simulated_experimental(
                    encoding=encoding,
                    adc_pattern=pattern,
                    gpio_pattern=pattern,
                    read_chunk_size=17,
                    write_chunk_size=3,
                    strict=True,
                    synchronization_retry_delay=0,
                ) as daq:
                    applied = daq.configure(encoding=encoding)
                    self.assertIs(encoding, applied.encoding)
                    daq.start()
                    blocks = tuple(daq.blocks(4))
                    status = daq.validate_stream_health()
                if not all(
                    isinstance(block, (ADCBlock, GPIOBlock)) for block in blocks
                ):
                    self.fail("simulator emitted a non-block stream item")
                captures[encoding] = blocks  # type: ignore[assignment]
                framed_bytes[encoding] = status.data_framed_bytes_transmitted

            raw = captures[ConfigurationEncoding.RAW]
            selected = captures[ConfigurationEncoding.RLE_AUTO]
            self.assertEqual(
                4 * constants.DATA_FRAME_BYTES, framed_bytes[ConfigurationEncoding.RAW]
            )
            self.assertLessEqual(
                framed_bytes[ConfigurationEncoding.RLE_AUTO],
                framed_bytes[ConfigurationEncoding.RAW],
            )
            for raw_block, selected_block in zip(raw, selected, strict=True):
                with self.subTest(
                    pattern=pattern.value,
                    kind=type(selected_block).__name__,
                    sequence=selected_block.sequence,
                ):
                    self.assertIs(type(raw_block), type(selected_block))
                    self.assertEqual(raw_block.payload, selected_block.payload)
                    self.assertEqual(raw_block.sequence, selected_block.sequence)
                    self.assertEqual(
                        raw_block.first_sample_ticks,
                        selected_block.first_sample_ticks,
                    )
                    self.assertIsNone(raw_block.encoding_diagnostics)
                    diagnostics = selected_block.encoding_diagnostics
                    self.assertIsNotNone(diagnostics)
                    assert diagnostics is not None

                    if isinstance(selected_block, ADCBlock):
                        expected = experimental_adc_payload(
                            pattern,
                            selected_block.first_pair_index,
                        )
                        item_size = constants.ADC_BYTES_PER_PAIR
                        maximum_items = constants.ADC_PAIRS_PER_FRAME
                        record_bytes = constants.ADC_RLE_RECORD_BYTES
                    else:
                        expected = experimental_gpio_payload(
                            pattern,
                            selected_block.first_sample_index,
                        )
                        item_size = 1
                        maximum_items = constants.GPIO_SAMPLES_PER_FRAME
                        record_bytes = constants.GPIO_RLE_RECORD_BYTES
                    self.assertEqual(expected, selected_block.payload)
                    run_count = count_rle_runs(
                        expected,
                        item_size=item_size,
                        max_items=maximum_items,
                    )
                    expected_selector = (
                        FrameEncoding.RLE
                        if run_count * record_bytes < constants.DATA_PAYLOAD_BYTES
                        else FrameEncoding.RAW
                    )
                    self.assertIs(expected_selector, diagnostics.frame_encoding)
                    self.assertEqual(run_count, diagnostics.run_count)


class RLECorpusBenchmarkGradingTests(unittest.TestCase):
    def test_corpus_is_repeatable_complete_and_uses_exact_frame_denominators(
        self,
    ) -> None:
        first = benchmark.build_rle_corpus(2)
        second = benchmark.build_rle_corpus(2)
        self.assertEqual(first, second)
        self.assertEqual(
            (
                "gpio-constant",
                "gpio-long-digital-holds",
                "gpio-sparse-single-bit-changes",
                "gpio-alternating-bytes",
                "gpio-pseudo-random-bytes",
                "adc-constant-pairs",
                "adc-independent-slow-channels",
                "adc-quantization-noise",
                "adc-high-entropy",
            ),
            tuple(workload.name for workload in first),
        )
        for workload in first:
            with self.subTest(workload=workload.name):
                self.assertEqual(2, len(workload.payloads))
                self.assertEqual(
                    2 * constants.DATA_PAYLOAD_BYTES,
                    workload.logical_payload_bytes,
                )
                self.assertEqual(
                    2 * workload.items_per_frame,
                    workload.logical_items,
                )
                self.assertTrue(
                    all(
                        len(payload) == constants.DATA_PAYLOAD_BYTES
                        for payload in workload.payloads
                    )
                )

    def test_production_corpus_passes_every_required_grade_and_break_even(self) -> None:
        with patch("thingdaq.rle_benchmark.perf_counter", return_value=0.0):
            result = benchmark.benchmark_rle_corpus(
                frames_per_workload=1,
                batch_count=1,
                iterations_per_batch=1,
                warmup_iterations=0,
            )
        self.assertTrue(result.passed)
        required = {check.name: check for check in result.checks if check.required}
        self.assertEqual(
            {
                "perfect_round_trip_equality",
                "rle_auto_no_expansion",
                "decode_throughput_headroom",
                "bounded_peak_working_memory",
                "strong_gpio_long_hold_savings",
                "incompressible_frames_fall_back_to_raw",
            },
            set(required),
        )
        self.assertTrue(all(check.passed for check in required.values()))

        report = benchmark.benchmark_report(result)
        break_even = {
            entry["stream"]: entry
            for entry in report["break_even"]  # type: ignore[index]
        }
        self.assertEqual(
            constants.ADC_RLE_MAX_SELECTED_RUNS,
            break_even["ADC"]["maximum_selected_run_records"],
        )
        self.assertEqual(
            constants.GPIO_RLE_MAX_SELECTED_RUNS,
            break_even["GPIO"]["maximum_selected_run_records"],
        )
        self.assertEqual(2, break_even["ADC"]["minimum_uniform_integer_run_items"])
        self.assertEqual(4, break_even["GPIO"]["minimum_uniform_integer_run_items"])

        for workload in result.workloads:
            with self.subTest(workload=workload.workload.name):
                self.assertTrue(workload.round_trip_equal)
                self.assertTrue(workload.no_expansion)
                if workload.workload.requires_raw_fallback:
                    self.assertEqual(
                        len(workload.workload.payloads),
                        workload.fallback_frames,
                    )

    def test_injected_selected_decode_corruption_fails_only_round_trip_grade(
        self,
    ) -> None:
        workload = benchmark.build_rle_corpus(1)[0]
        decode_case = benchmark._decode_case

        def corrupt_selected_decode(
            wire: bytes,
            encoding: ConfigurationEncoding,
        ) -> tuple[V2Frame, ADCBlock | GPIOBlock]:
            frame, block = decode_case(wire, encoding)
            if encoding is ConfigurationEncoding.RLE_AUTO:
                corrupted = bytearray(block.payload)
                corrupted[0] ^= 0x01
                block = replace(block, payload=bytes(corrupted))
            return frame, block

        with patch.object(
            benchmark,
            "_decode_case",
            side_effect=corrupt_selected_decode,
        ):
            framed = benchmark._frame_workload(workload, run_id=0x524C_45FF)
        self.assertTrue(framed)
        self.assertTrue(all(not frame.round_trip_equal for frame in framed))

        with patch("thingdaq.rle_benchmark.perf_counter", return_value=0.0):
            valid = benchmark.benchmark_rle_corpus(
                frames_per_workload=1,
                batch_count=1,
                iterations_per_batch=1,
                warmup_iterations=0,
            )
        corrupted_workloads = (
            replace(valid.workloads[0], round_trip_equal=False),
            *valid.workloads[1:],
        )
        checks = benchmark._grade(corrupted_workloads)
        states = {check.name: check.passed for check in checks if check.required}
        self.assertFalse(states["perfect_round_trip_equality"])
        self.assertTrue(states["rle_auto_no_expansion"])
        self.assertTrue(states["bounded_peak_working_memory"])
        self.assertTrue(states["incompressible_frames_fall_back_to_raw"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
