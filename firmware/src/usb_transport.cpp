#include "usb_transport.h"

#include <limits>

namespace teensy_daq::usb {
namespace {

template <typename Integer>
void saturatingAdd(Integer &value, Integer amount) {
  const Integer maximum = std::numeric_limits<Integer>::max();
  value = amount > maximum - value ? maximum : value + amount;
}

template <typename Integer>
void saturatingIncrement(Integer &value) {
  saturatingAdd(value, Integer{1U});
}

constexpr std::size_t minimum(std::size_t left, std::size_t right) {
  return left < right ? left : right;
}

std::uint32_t counterDelta(std::uint32_t current, std::uint32_t previous) {
  return current >= previous ? current - previous : current;
}

bool responseKind(protocol_v1::FrameKind kind) {
  switch (kind) {
    case protocol_v1::FrameKind::kInfoResponse:
    case protocol_v1::FrameKind::kConfigureResponse:
    case protocol_v1::FrameKind::kStartResponse:
    case protocol_v1::FrameKind::kGetStatusResponse:
    case protocol_v1::FrameKind::kStopResponse:
    case protocol_v1::FrameKind::kResetStatsResponse:
    case protocol_v1::FrameKind::kPingResponse:
    case protocol_v1::FrameKind::kChecksumBenchmarkResponse:
    case protocol_v1::FrameKind::kGpioClockDiagnosticResponse:
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticResponse:
    case protocol_v1::FrameKind::kErrorResponse:
      return true;
    case protocol_v1::FrameKind::kAdcData:
    case protocol_v1::FrameKind::kGpioData:
    case protocol_v1::FrameKind::kInfoRequest:
    case protocol_v1::FrameKind::kConfigureRequest:
    case protocol_v1::FrameKind::kStartRequest:
    case protocol_v1::FrameKind::kGetStatusRequest:
    case protocol_v1::FrameKind::kStopRequest:
    case protocol_v1::FrameKind::kResetStatsRequest:
    case protocol_v1::FrameKind::kPingRequest:
    case protocol_v1::FrameKind::kChecksumBenchmarkRequest:
    case protocol_v1::FrameKind::kGpioClockDiagnosticRequest:
    case protocol_v1::FrameKind::kGpioCaptureDiagnosticRequest:
      return false;
  }
  return false;
}

}  // namespace

ServiceReport CdcTransport::serviceReceive() {
  ServiceReport report{};
  bool stalled = false;

  while (report.bytes_processed < board::kUsbRxBudgetBytesPerLoop) {
    if (command_queue_.full()) {
      stalled = true;
      break;
    }

    if (rx_pending_offset_ < rx_pending_size_) {
      if (!processPendingReceive(report)) {
        stalled = true;
        break;
      }
      continue;
    }

    if (report.io_calls >= board::kUsbRxCallsPerLoop) {
      report.call_budget_exhausted = true;
      saturatingIncrement(counters_.rx_call_budget_exhaustions);
      break;
    }

    saturatingIncrement(counters_.rx_available_calls);
    const IoCount available = stream_.available();
    if (available < 0) {
      recordIoError();
      stalled = true;
      break;
    }
    if (available == 0) {
      break;
    }

    const std::size_t remaining_budget =
        board::kUsbRxBudgetBytesPerLoop - report.bytes_processed;
    const std::size_t requested =
        minimum(minimum(static_cast<std::size_t>(available),
                        rx_scratch_.size()),
                remaining_budget);
    if (requested == 0U) {
      break;
    }

    saturatingIncrement(counters_.rx_read_calls);
    ++report.io_calls;
    const IoCount received = stream_.read(rx_scratch_.data(), requested);
    if (received < 0) {
      recordIoError();
      stalled = true;
      break;
    }
    if (received == 0) {
      saturatingIncrement(counters_.zero_length_read_events);
      recordIoError();
      stalled = true;
      break;
    }

    std::size_t accepted = static_cast<std::size_t>(received);
    if (accepted > requested) {
      accepted = requested;
      recordIoError();
    }
    rx_pending_offset_ = 0U;
    rx_pending_size_ = accepted;
    report.bytes_read += accepted;
    saturatingAdd(counters_.rx_bytes,
                  static_cast<std::uint64_t>(accepted));
  }

  if (report.bytes_processed == board::kUsbRxBudgetBytesPerLoop) {
    report.byte_budget_exhausted = true;
    saturatingIncrement(counters_.rx_byte_budget_exhaustions);
  }
  if (stalled) {
    report.stalled = true;
    recordRxStall();
  } else if (report.bytes_read != 0U || report.bytes_processed != 0U) {
    counters_.consecutive_rx_stalls = 0U;
  }
  publishParserDelta();
  return report;
}

bool CdcTransport::processPendingReceive(ServiceReport &report) {
  if (rx_pending_offset_ >= rx_pending_size_) {
    rx_pending_offset_ = 0U;
    rx_pending_size_ = 0U;
    return true;
  }
  if (command_queue_.full()) {
    return false;
  }

  const std::size_t pending = rx_pending_size_ - rx_pending_offset_;
  const std::size_t budget =
      board::kUsbRxBudgetBytesPerLoop - report.bytes_processed;
  const std::size_t offered = minimum(pending, budget);
  if (offered == 0U) {
    return true;
  }

  protocol::ParsedCommand command{};
  const protocol::FeedResult fed = parser_.feed(
      {rx_scratch_.data() + rx_pending_offset_, offered}, command);
  if (fed.consumed == 0U) {
    recordIoError();
    return false;
  }

  rx_pending_offset_ += fed.consumed;
  report.bytes_processed += fed.consumed;
  saturatingAdd(counters_.rx_bytes_processed,
                static_cast<std::uint64_t>(fed.consumed));
  if (rx_pending_offset_ == rx_pending_size_) {
    rx_pending_offset_ = 0U;
    rx_pending_size_ = 0U;
  }

  if (fed.command_ready) {
    if (!command_queue_.push(command)) {
      recordIoError();
      return false;
    }
    saturatingIncrement(counters_.commands_queued);
    ++report.commands_queued;
    if (command_queue_.size() > command_queue_high_water_) {
      command_queue_high_water_ = command_queue_.size();
    }
  }
  return true;
}

ServiceReport CdcTransport::serviceTransmit() {
  ServiceReport report{};
  bool stalled = false;

  while (report.bytes_written < board::kUsbTxBudgetBytesPerVisit) {
    if (report.io_calls >= board::kUsbTxCallsPerVisit) {
      report.call_budget_exhausted = true;
      saturatingIncrement(counters_.tx_call_budget_exhaustions);
      break;
    }

    FrameSelection selection = selectTransmitFrame();
    if (selection.kind == ActiveFrame::kNone) {
      break;
    }
    if (!selection.bytes.valid() || selection.bytes.size == 0U ||
        tx_offset_ >= selection.bytes.size) {
      recordIoError();
      if (tx_offset_ == 0U) {
        completeTransmitFrame(selection.kind);
        continue;
      }
      stalled = true;
      break;
    }

    saturatingIncrement(counters_.tx_available_calls);
    const IoCount writable = stream_.availableForWrite();
    if (writable < 0) {
      recordIoError();
      stalled = true;
      break;
    }
    if (writable == 0) {
      stalled = true;
      break;
    }

    const std::size_t frame_remaining = selection.bytes.size - tx_offset_;
    const std::size_t budget_remaining =
        board::kUsbTxBudgetBytesPerVisit - report.bytes_written;
    const std::size_t minimum_write =
        minimum(frame_remaining, board::kUsbTxMinimumWriteBytes);
    if (budget_remaining < minimum_write) {
      report.byte_budget_exhausted = true;
      saturatingIncrement(counters_.tx_byte_budget_exhaustions);
      break;
    }
    if (static_cast<std::size_t>(writable) < minimum_write) {
      saturatingIncrement(counters_.short_capacity_deferrals);
      stalled = true;
      break;
    }
    if (tx_offset_ == 0U &&
        selection.kind == ActiveFrame::kLowerPriority) {
      if (lower_priority_ == nullptr ||
          !lower_priority_->prepareFrontFrame()) {
        recordIoError();
        stalled = true;
        break;
      }
      selection.bytes = lower_priority_->frontFrame();
      if (!selection.bytes.valid() ||
          selection.bytes.size != protocol_v1::kDataFrameBytes) {
        recordIoError();
        stalled = true;
        break;
      }
    }
    const std::size_t requested =
        minimum(minimum(minimum(frame_remaining, budget_remaining),
                        static_cast<std::size_t>(writable)),
                board::kUsbTxMaxWriteBytes);
    if (requested == 0U) {
      stalled = true;
      break;
    }

    saturatingAdd(counters_.tx_bytes_requested,
                  static_cast<std::uint64_t>(requested));
    if (requested > counters_.max_write_request_bytes) {
      counters_.max_write_request_bytes = requested;
    }
    saturatingIncrement(counters_.tx_write_calls);
    ++report.io_calls;
    const IoCount written =
        stream_.write(selection.bytes.data + tx_offset_, requested);
    if (written < 0) {
      recordIoError();
      stalled = true;
      break;
    }
    if (written == 0) {
      saturatingIncrement(counters_.zero_length_write_events);
      statistics_.recordTimeout();
      stalled = true;
      break;
    }

    std::size_t accepted = static_cast<std::size_t>(written);
    if (accepted > requested) {
      accepted = requested;
      recordIoError();
    }
    if (accepted < requested) {
      saturatingIncrement(counters_.partial_write_events);
      statistics_.recordPartialUsbWrite();
    }

    if (tx_offset_ == 0U && accepted < selection.bytes.size) {
      active_frame_ = selection.kind;
      if (selection.kind == ActiveFrame::kLowerPriority) {
        active_lower_priority_frame_ = selection.bytes;
      }
    }
    if (tx_offset_ == 0U && accepted != 0U &&
        selection.kind == ActiveFrame::kLowerPriority &&
        lower_priority_ != nullptr) {
      lower_priority_->markFrontFrameStarted();
    }
    tx_offset_ += accepted;
    report.bytes_written += accepted;
    saturatingAdd(counters_.tx_bytes,
                  static_cast<std::uint64_t>(accepted));

    if (tx_offset_ == selection.bytes.size) {
      completeTransmitFrame(selection.kind);
      ++report.frames_completed;
    }
  }

  if (report.bytes_written == board::kUsbTxBudgetBytesPerVisit &&
      hasPendingTransmission()) {
    report.byte_budget_exhausted = true;
    saturatingIncrement(counters_.tx_byte_budget_exhaustions);
  }
  if (stalled) {
    report.stalled = true;
    recordTxStall();
  } else if (report.bytes_written != 0U) {
    counters_.consecutive_tx_stalls = 0U;
  }
  return report;
}

bool CdcTransport::takeCommand(protocol::ParsedCommand &command) {
  if (command_awaiting_response_ || response_queue_.full() ||
      !command_queue_.pop(command)) {
    return false;
  }
  command_awaiting_response_ = true;
  saturatingIncrement(counters_.commands_dequeued);
  return true;
}

bool CdcTransport::queueResponse(const protocol::ControlFrame &response) {
  protocol::DecodedFrame decoded{};
  if (response.size() == 0U ||
      !protocol::decodeFrame(response.view(), decoded).ok() ||
      !responseKind(decoded.header.kind) || response_queue_.full() ||
      !response_queue_.push(response)) {
    saturatingIncrement(counters_.response_queue_rejections);
    recordIoError();
    return false;
  }
  command_awaiting_response_ = false;
  saturatingIncrement(counters_.responses_queued);
  if (response_queue_.size() > response_queue_high_water_) {
    response_queue_high_water_ = response_queue_.size();
  }
  return true;
}

bool CdcTransport::abandonResponseReservation() {
  if (!command_awaiting_response_) {
    return false;
  }
  command_awaiting_response_ = false;
  saturatingIncrement(counters_.response_reservations_abandoned);
  recordIoError();
  return true;
}

bool CdcTransport::hasPendingTransmission() const {
  if (active_frame_ != ActiveFrame::kNone || !response_queue_.empty()) {
    return true;
  }
  return lower_priority_ != nullptr &&
         lower_priority_->frontFrame().size != 0U;
}

TransportSnapshot CdcTransport::snapshot() const {
  TransportSnapshot result = counters_;
  result.command_queue_depth = command_queue_.size();
  result.response_queue_depth = response_queue_.size();
  result.lower_priority_queue_depth =
      lower_priority_ == nullptr ? 0U : lower_priority_->queuedFrames();
  result.command_queue_high_water = command_queue_high_water_;
  result.response_queue_high_water = response_queue_high_water_;
  result.pending_rx_bytes = rx_pending_size_ - rx_pending_offset_;
  result.active_frame_bytes_sent = tx_offset_;
  result.command_awaiting_response = command_awaiting_response_;
  if (active_frame_ == ActiveFrame::kResponse) {
    const protocol::ControlFrame *response = response_queue_.front();
    result.active_frame_size = response == nullptr ? 0U : response->size();
    result.active_frame_is_response = true;
  } else if (active_frame_ == ActiveFrame::kLowerPriority) {
    result.active_frame_size = active_lower_priority_frame_.size;
  }
  result.parser = parser_.counters();
  return result;
}

void CdcTransport::publishParserDelta() {
  const protocol::ParserCounters current = parser_.counters();
  protocol::ParserCounters delta{};
  delta.candidates_rejected = counterDelta(
      current.candidates_rejected,
      published_parser_counters_.candidates_rejected);
  delta.bad_versions = counterDelta(current.bad_versions,
                                    published_parser_counters_.bad_versions);
  delta.bad_kinds = counterDelta(current.bad_kinds,
                                 published_parser_counters_.bad_kinds);
  delta.bad_lengths = counterDelta(current.bad_lengths,
                                   published_parser_counters_.bad_lengths);
  delta.bad_checksums = counterDelta(
      current.bad_checksums, published_parser_counters_.bad_checksums);
  statistics_.recordParserDelta(delta);
  published_parser_counters_ = current;
}

CdcTransport::FrameSelection CdcTransport::selectTransmitFrame() {
  if (active_frame_ == ActiveFrame::kResponse) {
    protocol::ControlFrame *response = response_queue_.front();
    return {active_frame_, response == nullptr ? protocol::ByteView{}
                                                : response->view()};
  }
  if (active_frame_ == ActiveFrame::kLowerPriority) {
    return {active_frame_, active_lower_priority_frame_};
  }

  protocol::ControlFrame *response = response_queue_.front();
  if (response != nullptr) {
    return {ActiveFrame::kResponse, response->view()};
  }
  if (lower_priority_ == nullptr) {
    return {};
  }
  const protocol::ByteView lower = lower_priority_->frontFrame();
  if (lower.size == 0U) {
    return {};
  }
  if (!lower.valid() || lower.size != protocol_v1::kDataFrameBytes) {
    recordIoError();
    lower_priority_->releaseFrontFrame();
    return {};
  }
  return {ActiveFrame::kLowerPriority, lower};
}

void CdcTransport::completeTransmitFrame(ActiveFrame kind) {
  if (kind == ActiveFrame::kResponse) {
    if (!response_queue_.popFront()) {
      recordIoError();
    } else {
      saturatingIncrement(counters_.responses_completed);
    }
  } else if (kind == ActiveFrame::kLowerPriority) {
    if (lower_priority_ == nullptr) {
      recordIoError();
    } else {
      lower_priority_->releaseFrontFrame();
      saturatingIncrement(counters_.lower_priority_frames_completed);
    }
  }
  active_frame_ = ActiveFrame::kNone;
  active_lower_priority_frame_ = {};
  tx_offset_ = 0U;
}

void CdcTransport::recordIoError() {
  saturatingIncrement(counters_.io_errors);
  statistics_.recordTransportError();
}

void CdcTransport::recordRxStall() {
  saturatingIncrement(counters_.rx_stall_events);
  saturatingIncrement(counters_.consecutive_rx_stalls);
  if (counters_.consecutive_rx_stalls >
      counters_.max_consecutive_rx_stalls) {
    counters_.max_consecutive_rx_stalls =
        counters_.consecutive_rx_stalls;
  }
}

void CdcTransport::recordTxStall() {
  saturatingIncrement(counters_.tx_stall_events);
  saturatingIncrement(counters_.consecutive_tx_stalls);
  if (counters_.consecutive_tx_stalls >
      counters_.max_consecutive_tx_stalls) {
    counters_.max_consecutive_tx_stalls =
        counters_.consecutive_tx_stalls;
  }
}

}  // namespace teensy_daq::usb
