#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "protocol.h"
#include "statistics.h"

namespace thingdaq::usb {

// Signed counts let a board adapter distinguish a transient zero-length
// operation from an actual backend error without exceptions or allocation.
using IoCount = std::int32_t;

class CdcByteStream {
 public:
  virtual ~CdcByteStream() = default;

  // Portable fakes and transports without a control-line concept are always
  // open. The Teensy adapter overrides this with the CDC DTR state so the
  // runtime can recognize host-session boundaries without ever waiting for a
  // host to appear.
  virtual bool sessionOpen() const { return true; }
  virtual IoCount available() = 0;
  virtual IoCount read(std::uint8_t *destination, std::size_t capacity) = 0;
  virtual IoCount availableForWrite() = 0;
  virtual IoCount write(const std::uint8_t *source, std::size_t size) = 0;
};

// Future data-frame queues can implement this interface without moving their
// DMA-visible storage into the control transport. The front frame must remain
// a complete encoded protocol frame and remain immutable until
// releaseFrontFrame() is called. Command responses always win at a frame
// boundary, while a lower-priority frame that has emitted bytes is completed
// first so the CDC byte stream can never contain interleaved frames.
class LowerPriorityFrameSource {
 public:
  virtual ~LowerPriorityFrameSource() = default;

  virtual protocol::ByteView frontFrame() const = 0;
  // Finalize any metadata that became known after queue admission. This runs
  // only at a frame boundary and before byte zero is offered to USB.
  virtual bool prepareFrontFrame() { return true; }
  // Called exactly once after USB accepts the first byte of the current front
  // frame. Before this callback the complete frame is still unsent and may be
  // replaced by the source's pressure policy; afterward it must remain pinned
  // until releaseFrontFrame() observes the final byte.
  virtual void markFrontFrameStarted() {}
  // A host-session boundary cannot carry a partially emitted frame into the
  // next byte stream. Remove and loss-account the pinned front frame without
  // treating it as transmitted.
  virtual bool abortFrontFrame() = 0;
  virtual void releaseFrontFrame() = 0;
  virtual std::size_t queuedFrames() const = 0;
};

struct ServiceReport {
  std::size_t bytes_read = 0U;
  std::size_t bytes_processed = 0U;
  std::size_t bytes_written = 0U;
  std::size_t io_calls = 0U;
  std::size_t commands_queued = 0U;
  std::size_t frames_completed = 0U;
  bool stalled = false;
  bool byte_budget_exhausted = false;
  bool call_budget_exhausted = false;
};

struct TransportSnapshot {
  std::uint64_t rx_bytes = 0U;
  std::uint64_t rx_bytes_processed = 0U;
  std::uint64_t tx_bytes = 0U;
  std::uint64_t tx_bytes_requested = 0U;
  std::uint32_t rx_available_calls = 0U;
  std::uint32_t rx_read_calls = 0U;
  std::uint32_t tx_available_calls = 0U;
  std::uint32_t tx_write_calls = 0U;
  std::uint32_t commands_queued = 0U;
  std::uint32_t rejected_commands_queued = 0U;
  std::uint32_t commands_dequeued = 0U;
  std::uint32_t responses_queued = 0U;
  std::uint32_t responses_completed = 0U;
  std::uint32_t lower_priority_frames_completed = 0U;
  std::uint32_t response_queue_rejections = 0U;
  std::uint32_t response_reservations_abandoned = 0U;
  std::uint32_t partial_write_events = 0U;
  std::uint32_t short_capacity_deferrals = 0U;
  std::uint32_t zero_length_read_events = 0U;
  std::uint32_t zero_length_write_events = 0U;
  std::uint32_t rx_stall_events = 0U;
  std::uint32_t tx_stall_events = 0U;
  std::uint32_t consecutive_rx_stalls = 0U;
  std::uint32_t consecutive_tx_stalls = 0U;
  std::uint32_t max_consecutive_rx_stalls = 0U;
  std::uint32_t max_consecutive_tx_stalls = 0U;
  std::uint32_t rx_byte_budget_exhaustions = 0U;
  std::uint32_t rx_call_budget_exhaustions = 0U;
  std::uint32_t tx_byte_budget_exhaustions = 0U;
  std::uint32_t tx_call_budget_exhaustions = 0U;
  std::uint32_t io_errors = 0U;
  std::uint32_t session_open_events = 0U;
  std::uint32_t session_close_events = 0U;
  std::uint32_t session_commands_abandoned = 0U;
  std::uint32_t session_responses_abandoned = 0U;
  std::size_t command_queue_depth = 0U;
  std::size_t response_queue_depth = 0U;
  std::size_t lower_priority_queue_depth = 0U;
  std::size_t command_queue_high_water = 0U;
  std::size_t response_queue_high_water = 0U;
  std::size_t pending_rx_bytes = 0U;
  std::size_t active_frame_bytes_sent = 0U;
  std::size_t active_frame_size = 0U;
  std::size_t max_write_request_bytes = 0U;
  bool active_frame_is_response = false;
  bool command_awaiting_response = false;
  bool session_open = true;
  protocol::ParserCounters parser{};
};

namespace detail {

template <typename Item, std::size_t Capacity>
class FixedQueue {
 public:
  static_assert(Capacity > 0U);

  constexpr bool empty() const { return size_ == 0U; }
  constexpr bool full() const { return size_ == Capacity; }
  constexpr std::size_t size() const { return size_; }
  static constexpr std::size_t capacity() { return Capacity; }

  bool push(const Item &item) {
    if (full()) {
      return false;
    }
    storage_[tail_] = item;
    tail_ = (tail_ + 1U) % Capacity;
    ++size_;
    return true;
  }

  bool pop(Item &item) {
    if (empty()) {
      return false;
    }
    item = storage_[head_];
    popFront();
    return true;
  }

  Item *front() { return empty() ? nullptr : &storage_[head_]; }
  const Item *front() const {
    return empty() ? nullptr : &storage_[head_];
  }

  bool popFront() {
    if (empty()) {
      return false;
    }
    head_ = (head_ + 1U) % Capacity;
    --size_;
    return true;
  }

  // Remove one queued value without disturbing the relative order of any
  // survivor. Packet pressure uses this only for a complete frame that has not
  // begun transmission; normal FIFO service remains pop()/popFront().
  bool eraseFirst(const Item &item) {
    std::size_t found = size_;
    for (std::size_t offset = 0U; offset < size_; ++offset) {
      if (storage_[(head_ + offset) % Capacity] == item) {
        found = offset;
        break;
      }
    }
    if (found == size_) {
      return false;
    }
    for (std::size_t offset = found; offset + 1U < size_; ++offset) {
      storage_[(head_ + offset) % Capacity] =
          storage_[(head_ + offset + 1U) % Capacity];
    }
    tail_ = (tail_ + Capacity - 1U) % Capacity;
    --size_;
    return true;
  }

  constexpr void clear() {
    head_ = 0U;
    tail_ = 0U;
    size_ = 0U;
  }

 private:
  std::array<Item, Capacity> storage_{};
  std::size_t head_ = 0U;
  std::size_t tail_ = 0U;
  std::size_t size_ = 0U;
};

}  // namespace detail

class CdcTransport {
 public:
  CdcTransport(CdcByteStream &stream, stats::Statistics &statistics,
               LowerPriorityFrameSource *lower_priority = nullptr)
      : stream_(stream),
        statistics_(statistics),
        lower_priority_(lower_priority) {}

  ServiceReport serviceReceive();
  ServiceReport serviceTransmit();

  // A command is released only when its bounded response has a guaranteed
  // queue slot. The cooperative caller must dispatch it and queue exactly one
  // response before taking another command.
  bool takeCommand(protocol::ParsedCommand &command);
  bool queueResponse(const protocol::ControlFrame &response);

  // Last-resort recovery when the caller cannot construct any valid response
  // for a command it already took. Normal dispatch must always queue one.
  bool abandonResponseReservation();

  // Consume the edge raised when CDC DTR enters a new open session. Runtime
  // uses this to reset only session-scoped duplicate-request history.
  bool takeSessionStarted();

  constexpr std::size_t commandQueueDepth() const {
    return command_queue_.size();
  }
  constexpr std::size_t responseQueueDepth() const {
    return response_queue_.size();
  }
  constexpr std::size_t responseQueueFree() const {
    return response_queue_.capacity() - response_queue_.size();
  }
  bool hasPendingTransmission() const;

  TransportSnapshot snapshot() const;

 private:
  enum class ActiveFrame : std::uint8_t {
    kNone,
    kResponse,
    kLowerPriority,
  };

  struct FrameSelection {
    ActiveFrame kind = ActiveFrame::kNone;
    protocol::ByteView bytes{};
  };

  bool processPendingReceive(ServiceReport &report);
  void updateSessionState();
  void handleSessionTransition(bool observed_open);
  void resetSessionQueues();
  void publishParserDelta();
  FrameSelection selectTransmitFrame();
  void completeTransmitFrame(ActiveFrame kind);
  void recordIoError();
  void recordRxStall();
  void recordTxStall();

  CdcByteStream &stream_;
  stats::Statistics &statistics_;
  LowerPriorityFrameSource *lower_priority_ = nullptr;
  protocol::IncrementalCommandParser parser_{};
  detail::FixedQueue<protocol::ParsedCommand, board::kCommandQueueDepth>
      command_queue_{};
  detail::FixedQueue<protocol::ControlFrame, board::kResponseQueueDepth>
      response_queue_{};
  std::array<std::uint8_t, board::kUsbRxScratchBytes> rx_scratch_{};
  std::size_t rx_pending_offset_ = 0U;
  std::size_t rx_pending_size_ = 0U;
  ActiveFrame active_frame_ = ActiveFrame::kNone;
  protocol::ByteView active_lower_priority_frame_{};
  std::size_t tx_offset_ = 0U;
  std::size_t command_queue_high_water_ = 0U;
  std::size_t response_queue_high_water_ = 0U;
  bool command_awaiting_response_ = false;
  bool session_state_initialized_ = false;
  bool session_open_ = true;
  bool session_started_pending_ = false;
  protocol::ParserCounters published_parser_counters_{};
  TransportSnapshot counters_{};
};

static_assert(board::kCommandQueueDepth > 0U);
static_assert(board::kResponseQueueDepth > 0U);
static_assert(board::kUsbRxScratchBytes >=
              protocol_v2::kMaxCommandFrameBytes);
static_assert(board::kUsbRxBudgetBytesPerLoop > 0U);
static_assert(board::kUsbTxBudgetBytesPerVisit > 0U);
static_assert(board::kUsbTxMinimumWriteBytes > 1U);
static_assert(board::kUsbTxMinimumWriteBytes <=
              board::kUsbTxMaxWriteBytes);
static_assert(board::kUsbTxMaxWriteBytes <=
              board::kUsbTxBudgetBytesPerVisit);

}  // namespace thingdaq::usb
