#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "statistics.h"

namespace teensy_daq::gpio_capture {

inline constexpr std::uint8_t kOverflowDestination =
    static_cast<std::uint8_t>(board::kGpioRawDmaRingDepth);
inline constexpr std::uint8_t kInvalidDestination = 0xFFU;

enum class BufferState : std::uint8_t {
  kFree = 0U,
  kDmaActive = 1U,
  kDmaQueued = 2U,
  kReady = 3U,
  kPacking = 4U,
  kReleasing = 5U,
};

enum class OperationStatus : std::uint8_t {
  kOk,
  kAlreadyRunning,
  kNotRunning,
  kNotQuiescent,
  kInvalidCompletion,
  kNoReadyBuffer,
  kInvalidHandle,
  kInvalidDiagnosticLimit,
};

struct alignas(board::kCacheLineBytes) RawBuffer {
  std::array<std::uint32_t, protocol_v1::kGpioSamplesPerFrame> words{};
};

struct alignas(board::kCacheLineBytes) RawBufferStorage {
  std::array<RawBuffer, board::kGpioRawDmaRingDepth> buffers{};
};

// Pressure samples do not need retention. Repeated writes to one isolated
// cache line keep eDMA live without consuming another full raw buffer.
struct alignas(board::kCacheLineBytes) RawOverflowSink {
  std::array<std::uint32_t,
             board::kGpioRawDmaOverflowSinkBytes / sizeof(std::uint32_t)>
      words{};
};

class CacheMaintenance {
 public:
  virtual ~CacheMaintenance() = default;

  // DMA receive ownership discards any CPU cache lines without writing stale
  // data back. CPU ownership invalidates again after the completed transfer.
  virtual void discardBeforeDmaWrite(void *address, std::size_t bytes) = 0;
  virtual void invalidateBeforeCpuRead(void *address, std::size_t bytes) = 0;
};

class CriticalSection {
 public:
  virtual ~CriticalSection() = default;
  virtual std::uint32_t enter() = 0;
  virtual void exit(std::uint32_t token) = 0;
};

struct PrimeResult {
  OperationStatus status = OperationStatus::kNotQuiescent;
  std::uint8_t active_destination = kInvalidDestination;
  std::uint8_t queued_destination = kInvalidDestination;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct MajorLoopResult {
  OperationStatus status = OperationStatus::kInvalidCompletion;
  std::uint8_t completed_destination = kInvalidDestination;
  std::uint8_t active_destination = kInvalidDestination;
  std::uint8_t queued_destination = kInvalidDestination;
  std::uint64_t completed_first_sample = 0U;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct BufferHandle {
  const std::uint32_t *words = nullptr;
  std::uint64_t first_sample = 0U;
  std::uint32_t sample_count = 0U;
  std::uint32_t lease = 0U;
  std::uint8_t buffer_index = kInvalidDestination;

  constexpr bool valid() const {
    return words != nullptr &&
           buffer_index < board::kGpioRawDmaRingDepth && lease != 0U &&
           sample_count != 0U &&
           sample_count <= protocol_v1::kGpioSamplesPerFrame;
  }
};

struct AcquireResult {
  OperationStatus status = OperationStatus::kNoReadyBuffer;
  BufferHandle handle{};

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

// One virtual acquisition and release pair is permitted per completed DMA
// batch. The GPIO packer never dispatches through this boundary per sample or
// per pin; its hot mapping loop receives plain contiguous pointers.
class RawWordSource {
 public:
  virtual ~RawWordSource() = default;
  virtual AcquireResult acquireReady() = 0;
  virtual OperationStatus release(const BufferHandle &handle) = 0;
};

inline constexpr std::uint32_t kRawWordDiagnosticMaxSamples = 256U;
inline constexpr std::size_t kRawWordDiagnosticBytesPerSample =
    sizeof(std::uint32_t);

struct RawWordDiagnosticLease {
  BufferHandle owner{};
  const std::uint32_t *words = nullptr;
  std::uint32_t sample_count = 0U;

  constexpr bool valid() const {
    return owner.valid() && words == owner.words && sample_count != 0U &&
           sample_count <= owner.sample_count &&
           sample_count <= kRawWordDiagnosticMaxSamples;
  }
};

struct RawWordDiagnosticAcquireResult {
  OperationStatus status = OperationStatus::kNoReadyBuffer;
  RawWordDiagnosticLease lease{};

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

// Explicitly bounded internal troubleshooting access to GPIO2_PSR words. This
// class intentionally has no frame encoder or transport capability: the normal
// GPIO wire layout remains one packed byte per sample, never the 16 MB/s raw
// 32-bit format.
class BoundedRawWordDiagnostic final {
 public:
  explicit constexpr BoundedRawWordDiagnostic(RawWordSource &source)
      : source_(source) {}

  RawWordDiagnosticAcquireResult acquire(std::uint32_t sample_limit);
  OperationStatus release(const RawWordDiagnosticLease &lease);

 private:
  RawWordSource &source_;
};

struct StopReport {
  OperationStatus status = OperationStatus::kNotRunning;
  std::uint32_t active_samples_discarded = 0U;
  std::size_t ready_buffers_to_drain = 0U;
  std::size_t packing_buffers_to_release = 0U;

  constexpr bool ok() const { return status == OperationStatus::kOk; }
};

struct Snapshot {
  stats::GpioRawCaptureProgress progress{};
  std::array<BufferState, board::kGpioRawDmaRingDepth> buffer_states{};
  std::uint8_t active_destination = kInvalidDestination;
  std::uint8_t queued_destination = kInvalidDestination;
  std::size_t ready_depth = 0U;
  std::size_t packing_depth = 0U;
  std::uint32_t invariant_errors = 0U;
  bool running = false;
  bool quiescent = true;
};

// Portable ownership core shared by the target ISR and the future batch
// packer. Exactly one destination is active and one is queued ahead. When no
// consumer buffer is FREE, future major loops use the DMA-only overflow sink;
// READY/PACKING buffers are never selected for DMA.
class RawCaptureRing final : public RawWordSource {
 public:
  constexpr RawCaptureRing(RawBufferStorage &storage,
                           RawOverflowSink &overflow_sink,
                           CacheMaintenance &cache,
                           CriticalSection &critical)
      : storage_(storage),
        overflow_sink_(overflow_sink),
        cache_(cache),
        critical_(critical) {}

  RawCaptureRing(const RawCaptureRing &) = delete;
  RawCaptureRing &operator=(const RawCaptureRing &) = delete;

  PrimeResult prime();
  MajorLoopResult onMajorLoopComplete();
  AcquireResult acquireReady() override;
  OperationStatus release(const BufferHandle &handle) override;

  // The caller must first stop the hardware trigger and eDMA request. A
  // partially filled active destination is then accounted exactly; complete
  // READY buffers remain drainable and PACKING leases remain valid.
  StopReport stop(std::uint32_t active_samples);
  void recordHardwareError();

  Snapshot snapshot();
  bool quiescent();

  std::uint32_t *destinationWords(std::uint8_t destination);
  const std::uint32_t *destinationWords(std::uint8_t destination) const;

 private:
  struct BufferRecord {
    BufferState state = BufferState::kFree;
    std::uint64_t first_sample = 0U;
    std::uint32_t lease = 0U;
  };

  std::uint8_t takeFreeBuffer(BufferState state,
                              std::uint64_t first_sample);
  std::uint8_t scheduleFutureDestination();
  std::size_t countState(BufferState state) const;
  bool allBuffersFree() const;
  bool handleMatches(const BufferHandle &handle,
                     BufferState state) const;
  std::uint32_t allocateLease();
  void noteInvariantError();

  RawBufferStorage &storage_;
  RawOverflowSink &overflow_sink_;
  CacheMaintenance &cache_;
  CriticalSection &critical_;
  std::array<BufferRecord, board::kGpioRawDmaRingDepth> records_{};
  stats::GpioRawCaptureProgress progress_{};
  std::uint64_t active_first_sample_ = 0U;
  std::uint64_t queued_first_sample_ = 0U;
  std::uint64_t next_first_sample_ = 0U;
  std::uint32_t next_lease_ = 1U;
  std::uint32_t invariant_errors_ = 0U;
  std::size_t next_free_search_ = 0U;
  std::uint8_t active_destination_ = kInvalidDestination;
  std::uint8_t queued_destination_ = kInvalidDestination;
  bool running_ = false;
};

// Pure read-modify-write helper used by both target START and all STOP/error
// paths. GPIO2 direction is made safe before pads are switched from GPIO7.
inline void selectStandardGpioInputs(volatile std::uint32_t &gpr27,
                                     volatile std::uint32_t &gpio2_gdir) {
  gpio2_gdir = gpio2_gdir & ~board::kGpio2PsrCaptureMask;
  gpr27 = gpr27 & ~board::kGpio7ToGpio2Gpr27ClearMask;
}

static_assert(board::kGpioRawDmaRingDepth >= 2U);
static_assert(board::kGpioRawDmaRingDepth < kInvalidDestination);
static_assert(sizeof(RawBuffer) == board::kGpioRawDmaBufferBytes);
static_assert(alignof(RawBuffer) == board::kCacheLineBytes);
static_assert(sizeof(RawBufferStorage) == board::kGpioRawDmaRingBytes);
static_assert(alignof(RawBufferStorage) == board::kCacheLineBytes);
static_assert(sizeof(RawOverflowSink) ==
              board::kGpioRawDmaOverflowSinkBytes);
static_assert(alignof(RawOverflowSink) == board::kCacheLineBytes);
static_assert(kRawWordDiagnosticMaxSamples <
              protocol_v1::kGpioSamplesPerFrame);
static_assert(kRawWordDiagnosticBytesPerSample == 4U);

}  // namespace teensy_daq::gpio_capture
