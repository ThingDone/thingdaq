#include "checksum_benchmark.h"

#include <limits>

#include "checksum.h"

#if defined(__IMXRT1062__)
#define THINGDAQ_BENCHMARK_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define THINGDAQ_BENCHMARK_COLD_CODE(section_name)
#endif

namespace thingdaq::benchmark {
namespace {

volatile std::uint32_t g_published_digest = 0U;

constexpr std::size_t alignedCacheBytes(std::size_t input_bytes) {
  return board::alignUp(input_bytes, board::kCacheLineBytes);
}

constexpr checksum::Algorithm checksumAlgorithm(
    protocol_v1::ChecksumAlgorithm algorithm) {
  switch (algorithm) {
    case protocol_v1::ChecksumAlgorithm::kAdler32:
      return checksum::Algorithm::kAdler32;
    case protocol_v1::ChecksumAlgorithm::kCrc32c:
      return checksum::Algorithm::kCrc32c;
    case protocol_v1::ChecksumAlgorithm::kCrc32IsoHdlc:
      return checksum::Algorithm::kCrc32IsoHdlc;
    case protocol_v1::ChecksumAlgorithm::kNoneReserved:
      break;
  }
  return checksum::Algorithm::kAdler32;
}

template <typename Integer>
bool checkedAdd(Integer &destination, Integer amount) {
  if (amount > std::numeric_limits<Integer>::max() - destination) {
    return false;
  }
  destination += amount;
  return true;
}

void compilerBarrier(const void *address) {
#if defined(__GNUC__)
  __asm__ volatile("" : : "r"(address) : "memory");
#else
  (void)address;
#endif
}

void compilerBarrier(std::uint32_t value) {
#if defined(__GNUC__)
  __asm__ volatile("" : : "r"(value) : "memory");
#else
  (void)value;
#endif
}

std::uint32_t mixDigest(std::uint32_t digest, std::uint32_t checksum_value,
                        std::uint32_t operation_index) {
  digest ^= checksum_value + 0x9E3779B9U + (digest << 6U) + (digest >> 2U);
  digest ^= operation_index * 0x85EBCA6BU;
  return digest;
}

}  // namespace

std::uint32_t publishedDigest() { return g_published_digest; }

THINGDAQ_BENCHMARK_COLD_CODE(".flashmem.checksum_benchmark.prepare_vector")
bool Runner::prepareVector(const protocol::ChecksumBenchmarkRequest &request,
                           Buffer &buffer) {
  for (std::size_t index = 0U; index < buffer.bytes.size(); ++index) {
    buffer.bytes[index] =
        static_cast<std::uint8_t>((index * 37U + 11U) & 0xFFU);
  }

  if (request.vector ==
      protocol_v1::BenchmarkVector::kCanonical123456789) {
    constexpr std::array<std::uint8_t, 9U> canonical{
        '1', '2', '3', '4', '5', '6', '7', '8', '9'};
    for (std::size_t index = 0U; index < canonical.size(); ++index) {
      buffer.bytes[index] = canonical[index];
    }
  }

  if (request.vector != protocol_v1::BenchmarkVector::kFrameCoverage) {
    return true;
  }

  // Use the production in-place encoder to construct an actual framed GPIO
  // packet. The benchmark input ends immediately before its checksum trailer,
  // matching the exact header-plus-payload coverage used by packetization.
  protocol::FrameFields fields{};
  fields.kind = protocol_v1::FrameKind::kGpioData;
  fields.flags = static_cast<std::uint16_t>(
      static_cast<std::uint16_t>(protocol_v1::FrameFlag::kSynthetic) |
      static_cast<std::uint16_t>(protocol_v1::FrameFlag::kEpochStart));
  fields.checksum_algorithm = request.checksum_algorithm;
  fields.run_id = 1U;
  fields.sequence = 0U;
  fields.first_sample_ticks = 0U;
  fields.item_count =
      static_cast<std::uint32_t>(protocol_v1::kGpioSamplesPerFrame);
  return protocol::encodeDataFrameInPlace(
             fields, {buffer.bytes.data(), buffer.bytes.size()},
             protocol_v1::kDataPayloadBytes)
      .ok();
}

std::uint32_t Runner::calibrateTimerOverhead() {
  std::uint32_t minimum = std::numeric_limits<std::uint32_t>::max();
  for (std::uint16_t sample = 0U;
       sample < protocol_v1::kChecksumBenchmarkTimerCalibrationSamples;
       ++sample) {
    const std::uint32_t token = platform_.enterCritical();
    const std::uint32_t begin = platform_.readCycles();
    compilerBarrier(this);
    const std::uint32_t end = platform_.readCycles();
    platform_.exitCritical(token);
    const std::uint32_t elapsed = end - begin;
    if (elapsed < minimum) {
      minimum = elapsed;
    }
  }
  return minimum;
}

bool Runner::warm(const protocol::ChecksumBenchmarkRequest &request,
                  Buffer &buffer, std::size_t input_bytes) {
  std::uint32_t checksum_value = 0U;
  for (std::uint16_t operation = 0U;
       operation < protocol_v1::kChecksumBenchmarkWarmupOperations;
       ++operation) {
    if (request.cache_state ==
        protocol_v1::BenchmarkCacheState::kColdInvalidated) {
      platform_.invalidate(buffer.bytes.data(),
                           alignedCacheBytes(input_bytes));
    }
    compilerBarrier(buffer.bytes.data());
    const protocol::Result result = protocol::computeChecksum(
        request.checksum_algorithm,
        {buffer.bytes.data(), input_bytes}, checksum_value);
    compilerBarrier(checksum_value);
    if (!result.ok()) {
      return false;
    }
  }
  g_published_digest = checksum_value;
  return true;
}

bool Runner::measureChecksum(
    const protocol::ChecksumBenchmarkRequest &request, const Buffer &buffer,
    std::size_t input_bytes, std::uint32_t overhead_cycles,
    std::uint32_t &checksum_value, std::uint32_t &raw_cycles,
    std::uint32_t &net_cycles) {
  const std::uint32_t token = platform_.enterCritical();
  const std::uint32_t begin = platform_.readCycles();
  compilerBarrier(buffer.bytes.data());
  const protocol::Result result = protocol::computeChecksum(
      request.checksum_algorithm, {buffer.bytes.data(), input_bytes},
      checksum_value);
  compilerBarrier(checksum_value);
  const std::uint32_t end = platform_.readCycles();
  platform_.exitCritical(token);
  raw_cycles = end - begin;
  net_cycles = raw_cycles > overhead_cycles ? raw_cycles - overhead_cycles : 0U;
  return result.ok();
}

bool Runner::measureInvalidate(Buffer &buffer, std::size_t input_bytes,
                               std::uint32_t overhead_cycles,
                               std::uint32_t &net_cycles) {
  if (input_bytes == 0U) {
    return false;
  }
  const std::uint32_t token = platform_.enterCritical();
  const std::uint32_t begin = platform_.readCycles();
  platform_.invalidate(buffer.bytes.data(), alignedCacheBytes(input_bytes));
  const std::uint32_t end = platform_.readCycles();
  platform_.exitCritical(token);
  const std::uint32_t raw_cycles = end - begin;
  net_cycles = raw_cycles > overhead_cycles ? raw_cycles - overhead_cycles : 0U;
  return true;
}

THINGDAQ_BENCHMARK_COLD_CODE(".flashmem.checksum_benchmark.runner")
RunResult Runner::run(const protocol::ChecksumBenchmarkRequest &request) {
  RunResult result{};
  result.response.request = request;
  if (!protocol::validChecksumBenchmarkRequest(request)) {
    result.status = RunStatus::kInvalidRequest;
    return result;
  }

  std::uint32_t counter_hz = 0U;
  if (!platform_.beginCycleCounter(counter_hz) ||
      counter_hz != protocol_v1::kChecksumBenchmarkCycleCounterHz) {
    result.status = RunStatus::kCounterUnavailable;
    return result;
  }

  Buffer &buffer =
      request.memory_region ==
              protocol_v1::BenchmarkMemoryRegion::kDtcmPacket
          ? dtcm_buffer_
          : ocram_buffer_;
  if (!prepareVector(request, buffer)) {
    result.status = RunStatus::kFramePreparationFailed;
    return result;
  }
  const std::size_t input_bytes =
      static_cast<std::size_t>(protocol::benchmarkVectorBytes(request.vector));
  if (request.cache_state ==
      protocol_v1::BenchmarkCacheState::kColdInvalidated) {
    // Commit deterministic setup bytes to OCRAM once before warm-up. Repeated
    // invalidation costs below are the cache-state cost attributable to each
    // measured checksum, while this one-time preparation is intentionally not.
    platform_.flushDelete(buffer.bytes.data(), alignedCacheBytes(input_bytes));
  }

  const std::uint32_t overhead_cycles = calibrateTimerOverhead();
  if (!warm(request, buffer, input_bytes)) {
    result.status = RunStatus::kFramePreparationFailed;
    return result;
  }

  protocol::ChecksumBenchmarkResponse &response = result.response;
  response.cycle_counter_hz = counter_hz;
  response.timer_overhead_cycles = overhead_cycles;
  const checksum::Algorithm implementation =
      checksumAlgorithm(request.checksum_algorithm);
  response.implementation_code_bytes = static_cast<std::uint32_t>(
      checksum::implementationCodeBytes(implementation));
  response.table_bytes =
      static_cast<std::uint32_t>(checksum::tableBytes(implementation));
  response.working_ram_bytes = static_cast<std::uint32_t>(kWorkingRamBytes);
  response.min_batch_cycles = std::numeric_limits<std::uint32_t>::max();

  std::uint32_t digest = 0x811C9DC5U;
  std::uint32_t operation_index = 0U;
  for (std::uint16_t batch = 0U; batch < request.batch_count; ++batch) {
    std::uint64_t batch_cycles = 0U;
    for (std::uint16_t iteration = 0U;
         iteration < request.iterations_per_batch; ++iteration) {
      if (request.cache_state ==
          protocol_v1::BenchmarkCacheState::kColdInvalidated) {
        std::uint32_t setup_cycles = 0U;
        if (!measureInvalidate(buffer, input_bytes, overhead_cycles,
                               setup_cycles) ||
            !checkedAdd(response.cache_setup_cycles,
                        static_cast<std::uint64_t>(setup_cycles))) {
          result.status = RunStatus::kMeasurementOverflow;
          return result;
        }
      }

      std::uint32_t checksum_value = 0U;
      std::uint32_t raw_cycles = 0U;
      std::uint32_t net_cycles = 0U;
      if (!measureChecksum(request, buffer, input_bytes, overhead_cycles,
                           checksum_value, raw_cycles, net_cycles) ||
          !checkedAdd(response.raw_checksum_cycles,
                      static_cast<std::uint64_t>(raw_cycles)) ||
          !checkedAdd(response.net_checksum_cycles,
                      static_cast<std::uint64_t>(net_cycles)) ||
          !checkedAdd(batch_cycles, static_cast<std::uint64_t>(net_cycles))) {
        result.status = RunStatus::kMeasurementOverflow;
        return result;
      }
      digest = mixDigest(digest, checksum_value, operation_index++);
    }

    if (batch_cycles > std::numeric_limits<std::uint32_t>::max()) {
      result.status = RunStatus::kMeasurementOverflow;
      return result;
    }
    const std::uint32_t bounded_batch =
        static_cast<std::uint32_t>(batch_cycles);
    if (bounded_batch < response.min_batch_cycles) {
      response.min_batch_cycles = bounded_batch;
    }
    if (bounded_batch > response.max_batch_cycles) {
      response.max_batch_cycles = bounded_batch;
    }
  }

  response.deterministic_digest = digest;
  g_published_digest = digest;
  compilerBarrier(digest);
  if (!protocol::populateChecksumBenchmarkMetrics(response)) {
    result.status = RunStatus::kMeasurementOverflow;
    return result;
  }
  result.status = RunStatus::kOk;
  return result;
}

}  // namespace thingdaq::benchmark

#undef THINGDAQ_BENCHMARK_COLD_CODE
