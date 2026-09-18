"""Appended to isolated rig programs; never imported by the public SDK.

The harness injects CHECKSUM_EXPERIMENT_MODE. A zero trailer is deliberately
incompatible with ordinary data validation. It does not detect data corruption.
Control checksums, frame structure, sequences and loss accounting stay enabled.
"""


def _experiment_data_checksum(original):
    def compute(data, algorithm):
        if len(data) >= 44 and data[5] in (1, 2):
            return 0
        return original(data, algorithm)

    return compute


def _experiment_install(mode, namespace):
    if mode not in ("baseline", "unrolled", "none"):
        raise ValueError("unknown checksum experiment")
    if mode == "none":
        if "compute_checksum" in namespace:
            namespace["compute_checksum"] = _experiment_data_checksum(
                namespace["compute_checksum"]
            )
        else:
            from thingdone_daq import protocol_v2

            protocol_v2.compute_v2_checksum = _experiment_data_checksum(
                protocol_v2.compute_v2_checksum
            )


def _experiment_expand_adc(namespace):
    from dataclasses import replace

    # Independent expectations for the research wire format. Ordinary rig and
    # SDK constants remain unchanged; all continuity and loss checks still run.
    layouts = namespace["LAYOUTS"]
    layouts[namespace["AUX_INPUT"]] = replace(
        layouts[namespace["AUX_INPUT"]],
        adc_items_per_frame=1012,
        adc_payload_bytes=4048,
        adc_total_frame_bytes=4096,
    )
    profiles = tuple(
        replace(profile, input_coverage_ticks=1012 * profile.adc_period_ticks)
        for profile in namespace["PROFILES"]
    )
    namespace["PROFILES"] = profiles
    namespace["PROFILE_BY_VALUE"] = {p.value: p for p in profiles}
    namespace["PROFILE_BY_NAME"] = {p.name: p for p in profiles}


def _experiment_measure_host(original):
    import time

    def run(*args, **kwargs):
        started = time.monotonic()
        cpu = time.process_time()
        result = original(*args, **kwargs)
        result.metrics["host_acceptance_cpu_seconds"] = time.process_time() - cpu
        result.metrics["host_acceptance_wall_seconds"] = time.monotonic() - started
        return result

    return run


def _experiment_device_benchmarks():
    import dataclasses
    import os

    from thingdone_daq import (
        BenchmarkCacheState,
        BenchmarkMemoryRegion,
        BenchmarkVector,
        ChecksumAlgorithm,
        ChecksumBenchmarkRequest,
        ChecksumBenchmarkResult,
        ExpectedDeviceIdentity,
        ThingDAQ,
    )
    from thingdone_daq._generated import protocol_v2_constants as constants

    expected = ExpectedDeviceIdentity(
        hardware_serial=int(os.environ["EXPECTED_HARDWARE_SERIAL"]),
        build_id=os.environ["EXPECTED_BUILD_ID"],
        firmware_version=(1, 1, 0),
        protocol_version=2,
    )
    rows = []
    with ThingDAQ.open(os.environ["SERIAL_PORT"], expected_identity=expected) as daq:
        for region, cache in (
            (BenchmarkMemoryRegion.OCRAM_DMA, BenchmarkCacheState.HOT_OR_NATIVE),
            (BenchmarkMemoryRegion.OCRAM_DMA, BenchmarkCacheState.COLD_INVALIDATED),
            (BenchmarkMemoryRegion.DTCM_PACKET, BenchmarkCacheState.HOT_OR_NATIVE),
        ):
            for repeat in range(3):
                request = ChecksumBenchmarkRequest(
                    checksum_algorithm=ChecksumAlgorithm.ADLER32,
                    vector=BenchmarkVector.FRAME_COVERAGE,
                    memory_region=region,
                    cache_state=cache,
                    batch_count=1,
                    iterations_per_batch=8,
                )
                print(
                    f"CHECKSUM_PROGRESS region={region.name} cache={cache.name} repeat={repeat}",
                    flush=True,
                )
                response = daq._reader.request(
                    constants.FrameKind.CHECKSUM_BENCHMARK_REQUEST,
                    request.to_payload(),
                    protocol_version=2,
                )
                result = response.value
                assert isinstance(result, ChecksumBenchmarkResult), repr(response)
                rows.append({**dataclasses.asdict(result), "repeat": repeat})
    return rows


if "CHECKSUM_EXPERIMENT_MODE" in globals():
    import json as _experiment_json

    _experiment_mode = globals()["CHECKSUM_EXPERIMENT_MODE"]
    _experiment_install(_experiment_mode, globals())
    if globals().get("FRAME_EXPERIMENT", False):
        _experiment_expand_adc(globals())
    if "run_acceptance" in globals():
        run_acceptance = _experiment_measure_host(globals()["run_acceptance"])
    _experiment_original_main = globals()["main"]

    def main():
        status = _experiment_original_main()
        if "ThingDAQ" in globals():
            try:
                rows = _experiment_device_benchmarks()
            except Exception as error:  # noqa: BLE001 - retain device failures
                print(
                    "CHECKSUM_BENCHMARK "
                    + _experiment_json.dumps(
                        {
                            "mode": _experiment_mode,
                            "error": repr(error),
                        }
                    ),
                    flush=True,
                )
                return 1
            print(
                "CHECKSUM_BENCHMARK "
                + _experiment_json.dumps(
                    {
                        "mode": _experiment_mode,
                        "data_integrity_checked": _experiment_mode != "none",
                        "rows": rows,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        return status
