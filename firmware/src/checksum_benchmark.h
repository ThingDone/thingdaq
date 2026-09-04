#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "protocol.h"

namespace thingdaq::benchmark {

inline constexpr std::size_t kBufferBytes = protocol_v1::kDataFrameBytes;
inline constexpr std::size_t kWorkingRamBytes = 2U * kBufferBytes;

// One isolated cache-line-aligned allocation is used in each real memory
// region. The complete allocation may therefore be invalidated without
// collateral cache-line damage.
struct alignas(board::kCacheLineBytes) Buffer {
  std::array<std::uint8_t, kBufferBytes> bytes{};
};

static_assert(alignof(Buffer) == board::kCacheLineBytes);
static_assert(sizeof(Buffer) == kBufferBytes);

// A target may lease an equally sized byte range from another inactive
// owner. Keeping that lease as a view avoids manufacturing a second C++
// object at the same address.
struct BufferView {
  std::uint8_t *data = nullptr;
  std::size_t size = 0U;

  constexpr bool valid() const {
    return data != nullptr && size == kBufferBytes;
  }
};

inline BufferView bufferView(Buffer &buffer) {
  return {buffer.bytes.data(), buffer.bytes.size()};
}

// Hardware effects stay behind this narrow seam so all measurement arithmetic,
// vector construction, overflow handling, and optimization guards are covered
// by portable host tests. A critical-section token must restore the caller's
// prior interrupt state, rather than blindly enabling interrupts.
class Platform {
 public:
  virtual ~Platform() = default;
  virtual bool beginCycleCounter(std::uint32_t &frequency_hz) = 0;
  virtual std::uint32_t readCycles() = 0;
  virtual std::uint32_t enterCritical() = 0;
  virtual void exitCritical(std::uint32_t token) = 0;
  virtual void flushDelete(void *address, std::size_t size) = 0;
  virtual void invalidate(void *address, std::size_t size) = 0;
};

enum class RunStatus : std::uint8_t {
  kOk,
  kInvalidRequest,
  kCounterUnavailable,
  kFramePreparationFailed,
  kMeasurementOverflow,
};

struct RunResult {
  RunStatus status = RunStatus::kInvalidRequest;
  protocol::ChecksumBenchmarkResponse response{};

  constexpr bool ok() const { return status == RunStatus::kOk; }
};

class Runner {
 public:
  Runner(Platform &platform, Buffer &dtcm_buffer, Buffer &ocram_buffer)
      : Runner(platform, bufferView(dtcm_buffer), bufferView(ocram_buffer)) {}
  Runner(Platform &platform, BufferView dtcm_buffer,
         BufferView ocram_buffer)
      : platform_(platform),
        dtcm_buffer_(dtcm_buffer),
        ocram_buffer_(ocram_buffer) {}

  RunResult run(const protocol::ChecksumBenchmarkRequest &request);

 private:
  bool prepareVector(const protocol::ChecksumBenchmarkRequest &request,
                     BufferView buffer);
  std::uint32_t calibrateTimerOverhead();
  bool warm(const protocol::ChecksumBenchmarkRequest &request,
            BufferView buffer,
            std::size_t input_bytes);
  bool measureChecksum(const protocol::ChecksumBenchmarkRequest &request,
                       BufferView buffer, std::size_t input_bytes,
                       std::uint32_t overhead_cycles,
                       std::uint32_t &checksum, std::uint32_t &raw_cycles,
                       std::uint32_t &net_cycles);
  bool measureInvalidate(BufferView buffer, std::size_t input_bytes,
                         std::uint32_t overhead_cycles,
                         std::uint32_t &net_cycles);

  Platform &platform_;
  BufferView dtcm_buffer_{};
  BufferView ocram_buffer_{};
};

// Volatile publication plus compiler barriers make every measured result
// observable and prevent a whole benchmark loop from being folded away.
std::uint32_t publishedDigest();

}  // namespace thingdaq::benchmark
