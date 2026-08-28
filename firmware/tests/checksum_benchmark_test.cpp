#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "checksum_benchmark.h"

namespace {

namespace benchmark = teensy_daq::benchmark;
namespace constants = teensy_daq::protocol_v1;
namespace protocol = teensy_daq::protocol;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

class FakePlatform final : public benchmark::Platform {
 public:
  bool counter_available = true;
  std::uint32_t counter_frequency =
      constants::kChecksumBenchmarkCycleCounterHz;
  std::uint32_t counter = std::numeric_limits<std::uint32_t>::max() - 50U;
  std::uint32_t calibration_elapsed = 4U;
  std::uint32_t checksum_elapsed = 104U;
  std::uint32_t invalidation_elapsed = 44U;
  std::uint32_t critical_entries = 0U;
  std::uint32_t critical_exits = 0U;
  std::uint32_t flush_delete_calls = 0U;
  std::uint32_t invalidate_calls = 0U;
  std::size_t last_cache_size = 0U;
  bool in_critical = false;

  bool beginCycleCounter(std::uint32_t &frequency_hz) override {
    read_pairs_ = 0U;
    pair_open_ = false;
    override_elapsed_ = 0U;
    frequency_hz = counter_frequency;
    return counter_available;
  }

  std::uint32_t readCycles() override {
    if (!pair_open_) {
      pair_open_ = true;
      return counter;
    }
    const std::uint32_t elapsed =
        override_elapsed_ != 0U
            ? override_elapsed_
            : (read_pairs_ <
                       constants::kChecksumBenchmarkTimerCalibrationSamples
                   ? calibration_elapsed
                   : checksum_elapsed);
    counter += elapsed;
    ++read_pairs_;
    pair_open_ = false;
    override_elapsed_ = 0U;
    return counter;
  }

  std::uint32_t enterCritical() override {
    expect(!in_critical, "critical sections do not nest");
    in_critical = true;
    ++critical_entries;
    return 0xA5A5U;
  }

  void exitCritical(std::uint32_t token) override {
    expect(in_critical, "critical exit follows an entry");
    expect(token == 0xA5A5U, "critical token is restored exactly");
    in_critical = false;
    ++critical_exits;
  }

  void flushDelete(void *address, std::size_t size) override {
    expect(address != nullptr, "cache flush has an address");
    expect(size % 32U == 0U, "cache flush covers complete lines");
    ++flush_delete_calls;
    last_cache_size = size;
  }

  void invalidate(void *address, std::size_t size) override {
    expect(address != nullptr, "cache invalidation has an address");
    expect(size % 32U == 0U, "cache invalidation covers complete lines");
    ++invalidate_calls;
    last_cache_size = size;
    if (pair_open_) {
      override_elapsed_ = invalidation_elapsed;
    }
  }

 private:
  std::uint32_t read_pairs_ = 0U;
  std::uint32_t override_elapsed_ = 0U;
  bool pair_open_ = false;
};

protocol::ChecksumBenchmarkRequest request(
    constants::ChecksumAlgorithm algorithm,
    constants::BenchmarkVector vector,
    constants::BenchmarkMemoryRegion region =
        constants::BenchmarkMemoryRegion::kDtcmPacket,
    constants::BenchmarkCacheState cache =
        constants::BenchmarkCacheState::kHotOrNative,
    std::uint16_t batches = 2U, std::uint16_t iterations = 3U) {
  protocol::ChecksumBenchmarkRequest value{};
  value.checksum_algorithm = algorithm;
  value.vector = vector;
  value.memory_region = region;
  value.cache_state = cache;
  value.batch_count = batches;
  value.iterations_per_batch = iterations;
  return value;
}

std::uint32_t expectedDigest(std::uint32_t checksum,
                             std::uint32_t operations) {
  std::uint32_t digest = 0x811C9DC5U;
  for (std::uint32_t operation = 0U; operation < operations; ++operation) {
    digest ^= checksum + 0x9E3779B9U + (digest << 6U) + (digest >> 2U);
    digest ^= operation * 0x85EBCA6BU;
  }
  return digest;
}

void testHotCanonicalAndCounterWrap() {
  FakePlatform platform{};
  benchmark::Buffer dtcm{};
  benchmark::Buffer ocram{};
  benchmark::Runner runner{platform, dtcm, ocram};
  const benchmark::RunResult result = runner.run(request(
      constants::ChecksumAlgorithm::kAdler32,
      constants::BenchmarkVector::kCanonical123456789));

  expect(result.ok(), "hot canonical benchmark succeeds");
  const protocol::ChecksumBenchmarkResponse &response = result.response;
  expect(response.buffer_bytes == 9U && response.processed_bytes == 54U,
         "canonical benchmark reports exact processed bytes");
  expect(response.timer_overhead_cycles == 4U &&
             response.raw_checksum_cycles == 624U &&
             response.net_checksum_cycles == 600U,
         "calibrated timer overhead is subtracted per operation");
  expect(response.min_batch_cycles == 300U &&
             response.max_batch_cycles == 300U,
         "repeated batch extrema report net checksum cycles");
  expect(response.cache_setup_cycles == 0U,
         "native DTCM has no cache-maintenance charge");
  expect(response.deterministic_digest ==
             expectedDigest(0x091E01DEU, 6U),
         "digest retains every canonical checksum result");
  expect(benchmark::publishedDigest() == response.deterministic_digest,
         "volatile digest publication prevents dead-code elimination");
  expect(platform.critical_entries == platform.critical_exits &&
             !platform.in_critical,
         "benchmark restores interrupt state after counter wrap");
  expect(response.implementation_code_bytes > 0U &&
             response.table_bytes == 0U &&
             response.working_ram_bytes == 8192U,
         "benchmark reports implementation and fixed working-set bytes");
}

void testColdOcramSeparatesCacheSetup() {
  FakePlatform platform{};
  benchmark::Buffer dtcm{};
  benchmark::Buffer ocram{};
  benchmark::Runner runner{platform, dtcm, ocram};
  const benchmark::RunResult result = runner.run(request(
      constants::ChecksumAlgorithm::kCrc32c,
      constants::BenchmarkVector::kBuffer64,
      constants::BenchmarkMemoryRegion::kOcramDma,
      constants::BenchmarkCacheState::kColdInvalidated, 1U, 2U));

  expect(result.ok(), "cold OCRAM benchmark succeeds");
  expect(platform.flush_delete_calls == 1U,
         "cold OCRAM commits setup bytes before warm-up");
  expect(platform.invalidate_calls ==
             constants::kChecksumBenchmarkWarmupOperations + 2U,
         "cold OCRAM invalidates before every warm and measured read");
  expect(platform.last_cache_size == 64U,
         "64-byte vector invalidates two isolated cache lines");
  expect(result.response.net_checksum_cycles == 200U &&
             result.response.cache_setup_cycles == 80U,
         "checksum and recurring cache setup cycles remain separate");
  expect(result.response.table_bytes == 1024U,
         "CRC benchmark reports its flash lookup table");
  const std::uint64_t total_cycles =
      result.response.net_checksum_cycles +
      result.response.cache_setup_cycles;
  expect(result.response.cycles_per_byte_q16 ==
             (total_cycles * 65536ULL) / result.response.processed_bytes,
         "cold throughput includes its recurring cache setup cost");
}

void testFullFrameUsesProductionCoverage() {
  FakePlatform platform{};
  benchmark::Buffer dtcm{};
  benchmark::Buffer ocram{};
  benchmark::Runner runner{platform, dtcm, ocram};
  const benchmark::RunResult result = runner.run(request(
      constants::ChecksumAlgorithm::kCrc32IsoHdlc,
      constants::BenchmarkVector::kFrameCoverage,
      constants::BenchmarkMemoryRegion::kDtcmPacket,
      constants::BenchmarkCacheState::kHotOrNative, 1U, 1U));

  expect(result.ok() && result.response.buffer_bytes == 4092U,
         "full-frame vector reports exact header-plus-payload coverage");
  protocol::DecodedFrame decoded{};
  const protocol::Result decoded_result = protocol::decodeFrame(
      {dtcm.bytes.data(), dtcm.bytes.size()}, decoded);
  expect(decoded_result.ok() &&
             decoded.header.kind == constants::FrameKind::kGpioData &&
             decoded.header.checksum_algorithm ==
                 constants::ChecksumAlgorithm::kCrc32IsoHdlc &&
             decoded.header.payload_length == constants::kDataPayloadBytes,
         "full-frame buffer is a valid production-encoded GPIO frame");
}

void testHotOcram512Vector() {
  FakePlatform platform{};
  benchmark::Buffer dtcm{};
  benchmark::Buffer ocram{};
  benchmark::Runner runner{platform, dtcm, ocram};
  const benchmark::RunResult result = runner.run(request(
      constants::ChecksumAlgorithm::kAdler32,
      constants::BenchmarkVector::kBuffer512,
      constants::BenchmarkMemoryRegion::kOcramDma,
      constants::BenchmarkCacheState::kHotOrNative, 1U, 2U));

  expect(result.ok() && result.response.buffer_bytes == 512U &&
             result.response.processed_bytes == 1024U,
         "hot OCRAM benchmark covers the aligned 512-byte vector");
  expect(platform.flush_delete_calls == 0U &&
             platform.invalidate_calls == 0U &&
             result.response.cache_setup_cycles == 0U,
         "hot OCRAM incurs no explicit cache-maintenance setup");
}

void testEmptyBoundsAndCounterFailure() {
  FakePlatform platform{};
  benchmark::Buffer dtcm{};
  benchmark::Buffer ocram{};
  benchmark::Runner runner{platform, dtcm, ocram};
  const benchmark::RunResult empty = runner.run(request(
      constants::ChecksumAlgorithm::kAdler32,
      constants::BenchmarkVector::kEmpty));
  expect(empty.ok() && empty.response.processed_bytes == 0U &&
             empty.response.cycles_per_byte_q16 == 0U &&
             empty.response.mb_per_second_q16 == 0U &&
             empty.response.projected_cpu_percent_q16 == 0U,
         "empty vector keeps byte-derived metrics unambiguous");

  const protocol::ChecksumBenchmarkRequest invalid = request(
      constants::ChecksumAlgorithm::kAdler32,
      constants::BenchmarkVector::kBuffer64,
      constants::BenchmarkMemoryRegion::kDtcmPacket,
      constants::BenchmarkCacheState::kColdInvalidated);
  const std::uint32_t entries_before = platform.critical_entries;
  expect(runner.run(invalid).status == benchmark::RunStatus::kInvalidRequest &&
             platform.critical_entries == entries_before,
         "meaningless cold DTCM request is rejected before measurement");

  platform.counter_available = false;
  expect(runner.run(request(constants::ChecksumAlgorithm::kAdler32,
                            constants::BenchmarkVector::kBuffer512))
             .status == benchmark::RunStatus::kCounterUnavailable,
         "unavailable cycle counter fails closed");
  platform.counter_available = true;
  platform.counter_frequency = 599999999U;
  expect(runner.run(request(constants::ChecksumAlgorithm::kAdler32,
                            constants::BenchmarkVector::kBuffer512))
             .status == benchmark::RunStatus::kCounterUnavailable,
         "a cycle counter at any frequency other than 600 MHz fails closed");

  const protocol::ChecksumBenchmarkRequest bounded = request(
      constants::ChecksumAlgorithm::kAdler32,
      constants::BenchmarkVector::kFrameCoverage,
      constants::BenchmarkMemoryRegion::kDtcmPacket,
      constants::BenchmarkCacheState::kHotOrNative, 8U, 256U);
  const protocol::ChecksumBenchmarkRequest oversized = request(
      constants::ChecksumAlgorithm::kAdler32,
      constants::BenchmarkVector::kFrameCoverage,
      constants::BenchmarkMemoryRegion::kDtcmPacket,
      constants::BenchmarkCacheState::kHotOrNative, 8U, 257U);
  expect(protocol::validChecksumBenchmarkRequest(bounded) &&
             !protocol::validChecksumBenchmarkRequest(oversized),
         "full-frame repetition bound caps processed work near eight MiB");
}

void testRepeatabilityAndCheckedMeasurementOverflow() {
  FakePlatform platform{};
  benchmark::Buffer dtcm{};
  benchmark::Buffer ocram{};
  benchmark::Runner runner{platform, dtcm, ocram};
  const protocol::ChecksumBenchmarkRequest repeated_request = request(
      constants::ChecksumAlgorithm::kCrc32c,
      constants::BenchmarkVector::kBuffer64,
      constants::BenchmarkMemoryRegion::kDtcmPacket,
      constants::BenchmarkCacheState::kHotOrNative, 2U, 3U);

  const benchmark::RunResult first = runner.run(repeated_request);
  const benchmark::RunResult second = runner.run(repeated_request);
  expect(first.ok() && second.ok() &&
             first.response.raw_checksum_cycles ==
                 second.response.raw_checksum_cycles &&
             first.response.net_checksum_cycles ==
                 second.response.net_checksum_cycles &&
             first.response.min_batch_cycles ==
                 second.response.min_batch_cycles &&
             first.response.max_batch_cycles ==
                 second.response.max_batch_cycles &&
             first.response.deterministic_digest ==
                 second.response.deterministic_digest &&
             benchmark::publishedDigest() ==
                 second.response.deterministic_digest,
         "identical inputs and cycle traces produce repeatable metrics/digest");

  platform.checksum_elapsed = std::numeric_limits<std::uint32_t>::max();
  const benchmark::RunResult overflow = runner.run(request(
      constants::ChecksumAlgorithm::kAdler32,
      constants::BenchmarkVector::kBuffer64,
      constants::BenchmarkMemoryRegion::kDtcmPacket,
      constants::BenchmarkCacheState::kHotOrNative, 1U, 2U));
  expect(overflow.status == benchmark::RunStatus::kMeasurementOverflow,
         "wrapped 32-bit intervals fail closed when one batch exceeds u32");
  expect(platform.critical_entries == platform.critical_exits &&
             !platform.in_critical,
         "measurement-overflow handling still restores interrupt state");
}

void testRigFixedVectorDigestsMatchProductionRunner() {
  struct VectorChecks {
    constants::BenchmarkVector vector;
    std::array<std::uint32_t, 3U> checksum;
  };
  constexpr std::array<constants::ChecksumAlgorithm, 3U> algorithms{
      constants::ChecksumAlgorithm::kAdler32,
      constants::ChecksumAlgorithm::kCrc32c,
      constants::ChecksumAlgorithm::kCrc32IsoHdlc,
  };
  constexpr std::array<VectorChecks, 5U> checks{{
      {constants::BenchmarkVector::kEmpty,
       {0x00000001U, 0x00000000U, 0x00000000U}},
      {constants::BenchmarkVector::kCanonical123456789,
       {0x091E01DEU, 0xE3069283U, 0xCBF43926U}},
      {constants::BenchmarkVector::kBuffer64,
       {0xF7ED2021U, 0x3D0F7D5DU, 0xFFBAE609U}},
      {constants::BenchmarkVector::kBuffer512,
       {0xC4E2FF01U, 0x724B2C2FU, 0xFF1346DBU}},
      {constants::BenchmarkVector::kFrameCoverage,
       {0x4F2DE54EU, 0xBFC9BB50U, 0xBEA7D1EDU}},
  }};

  FakePlatform platform{};
  benchmark::Buffer dtcm{};
  benchmark::Buffer ocram{};
  benchmark::Runner runner{platform, dtcm, ocram};
  for (const VectorChecks &vector : checks) {
    for (std::size_t algorithm_index = 0U;
         algorithm_index < algorithms.size(); ++algorithm_index) {
      const benchmark::RunResult result = runner.run(request(
          algorithms[algorithm_index], vector.vector,
          constants::BenchmarkMemoryRegion::kDtcmPacket,
          constants::BenchmarkCacheState::kHotOrNative, 1U, 2U));
      expect(result.ok() &&
                 result.response.deterministic_digest ==
                     expectedDigest(vector.checksum[algorithm_index], 2U),
             "rig fixed vector checksum/digest matches production runner");
    }
  }
}

}  // namespace

int main() {
  testHotCanonicalAndCounterWrap();
  testColdOcramSeparatesCacheSetup();
  testFullFrameUsesProductionCoverage();
  testHotOcram512Vector();
  testEmptyBoundsAndCounterFailure();
  testRepeatabilityAndCheckedMeasurementOverflow();
  testRigFixedVectorDigestsMatchProductionRunner();
  if (failures != 0) {
    std::cerr << failures << " checksum benchmark assertion(s) failed\n";
    return 1;
  }
  return 0;
}
