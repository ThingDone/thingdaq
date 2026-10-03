"""Bounded protocol-v2 Adler experiment using the Phase-05 benchmark shape."""

from __future__ import annotations

import json
import os

from thingdone_daq import ExpectedDeviceIdentity, ThingDAQ
from thingdone_daq._generated import protocol_constants as v1
from thingdone_daq._generated import protocol_v2_constants as v2
from thingdone_daq.models import ChecksumBenchmarkRequest, ChecksumBenchmarkResult


def main() -> int:
    evidence: dict[str, object] = {
        "result": "FAIL",
        "method": "phase-05-frame-coverage-4x256",
        "measurements": [],
        "electrical_stimulus": "NOT_CONNECTED",
    }
    try:
        expected = ExpectedDeviceIdentity(
            hardware_serial=int(os.environ["EXPECTED_HARDWARE_SERIAL"]),
            build_id=os.environ["EXPECTED_BUILD_ID"],
            firmware_version=(1, 1, 0),
            protocol_version=2,
        )
        with ThingDAQ.open(
            os.environ["SERIAL_PORT"], expected_identity=expected, strict=True
        ) as daq:
            info = daq.info()
            required_mask = sum(
                1 << int(algorithm)
                for algorithm in (
                    v1.ChecksumAlgorithm.ADLER32,
                    v1.ChecksumAlgorithm.ADLER32_DUAL_LANE,
                )
            )
            assert info.supported_checksum_mask & required_mask == required_mask
            health = daq.get_runtime_health()
            assert health.stack_available and health.stack_min_free_bytes > 0
            assert not health.watchdog_enabled and health.watchdog_timeout_ms == 0
            evidence["runtime_health"] = {
                "stack_min_free_bytes": health.stack_min_free_bytes,
                "watchdog_enabled": health.watchdog_enabled,
                "watchdog_timeout_ms": health.watchdog_timeout_ms,
            }
            for algorithm in (
                v1.ChecksumAlgorithm.ADLER32,
                v1.ChecksumAlgorithm.ADLER32_DUAL_LANE,
            ):
                for region, cache in (
                    (
                        v1.BenchmarkMemoryRegion.DTCM_PACKET,
                        v1.BenchmarkCacheState.HOT_OR_NATIVE,
                    ),
                    (
                        v1.BenchmarkMemoryRegion.OCRAM_DMA,
                        v1.BenchmarkCacheState.COLD_INVALIDATED,
                    ),
                ):
                    request = ChecksumBenchmarkRequest(
                        checksum_algorithm=algorithm,
                        vector=v1.BenchmarkVector.FRAME_COVERAGE,
                        memory_region=region,
                        cache_state=cache,
                        batch_count=4,
                        iterations_per_batch=256,
                    )
                    response = daq._command(
                        v2.FrameKind.CHECKSUM_BENCHMARK_REQUEST,
                        request.to_payload(),
                        timeout=10.0,
                        protocol_version=2,
                    )
                    assert isinstance(response.value, ChecksumBenchmarkResult)
                    result = response.value
                    assert result.request == request
                    evidence["measurements"].append(
                        {
                            "algorithm": algorithm.name,
                            "memory_region": region.name,
                            "cache_state": cache.name,
                            "buffer_bytes": result.buffer_bytes,
                            "cycles_per_byte": result.cycles_per_byte,
                            "mb_per_second": result.mb_per_second,
                            "projected_cpu_percent": result.projected_cpu_percent,
                            "implementation_code_bytes": (
                                result.implementation_code_bytes
                            ),
                            "table_bytes": result.table_bytes,
                            "min_batch_cycles": result.min_batch_cycles,
                            "max_batch_cycles": result.max_batch_cycles,
                        }
                    )
            evidence["result"] = "PASS"
    except Exception as error:  # noqa: BLE001 - preserve remote evidence
        evidence["error"] = f"{type(error).__name__}: {error}"
    print("EVIDENCE " + json.dumps(evidence, sort_keys=True), flush=True)
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
