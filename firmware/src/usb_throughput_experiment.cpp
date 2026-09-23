#include "usb_throughput_experiment.h"

#if defined(THINGDAQ_EXPERIMENT_USB_THROUGHPUT)
#include <Arduino.h>
#include <cstring>

extern volatile uint8_t usb_high_speed;

namespace thingdaq::usb_throughput {
namespace {
constexpr std::size_t kHeader = 32;
bool enabled = true;
struct State {
  char command[80]{};
  std::size_t command_size = 0;
  std::uint32_t run = 0, sequence = 0, mode = 0, duration_us = 0;
  std::uint32_t rate = 0, started = 0, transfer_size = 0, offset = 0;
  std::uint64_t bytes = 0, calls = 0, active_us = 0, short_writes = 0;
  bool running = false, stop = false;
} state;

FLASHMEM void put32(std::uint8_t *p, std::uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) p[i] = static_cast<std::uint8_t>(value >> (8U * i));
}
FLASHMEM void put64(std::uint8_t *p, std::uint64_t value) {
  put32(p, static_cast<std::uint32_t>(value));
  put32(p + 4, static_cast<std::uint32_t>(value >> 32U));
}
FLASHMEM void header(std::uint8_t *p, const char *magic, std::uint32_t seq,
                     std::uint32_t size, std::uint32_t kind,
                     std::uint32_t adc, std::uint32_t gpio) {
  std::memcpy(p, magic, 8);
  put32(p + 8, state.run); put32(p + 12, seq); put32(p + 16, size);
  put32(p + 20, kind); put32(p + 24, adc); put32(p + 28, gpio);
}
FLASHMEM void dataHeader(std::uint8_t *p, std::uint32_t seq, std::uint32_t size) {
  const bool combined = state.mode == 5;
  const bool adc = (state.mode == 3 || state.mode == 4) && seq % 3U < 2U;
  const std::uint32_t payload = size - kHeader;
  const std::uint32_t adc_bytes = combined ? payload * 2U / 3U : (adc ? payload : 0U);
  header(p, "TDATA001", seq, size, combined ? 3U : (adc ? 1U : 2U),
         adc_bytes, payload - adc_bytes);
}
FLASHMEM void finish(usb::TeensyCdcByteStream &stream, std::uint8_t *buffer) {
  const auto elapsed = static_cast<std::uint32_t>(micros() - state.started);
  header(buffer, "TDEND001", state.sequence, 96, state.mode, 0, 0);
  put64(buffer + 32, state.bytes); put64(buffer + 40, elapsed);
  put64(buffer + 48, state.calls); put64(buffer + 56, state.active_us);
  put64(buffer + 64, state.sequence); put64(buffer + 72, state.short_writes);
  put64(buffer + 80, state.rate); put64(buffer + 88, state.stop ? 2 : 1);
  state.running = false;
  (void)stream.write(buffer, 96);
}
FLASHMEM bool parseRun(const char *p, std::uint32_t (&values)[3]) {
  if (std::strncmp(p, "RUN ", 4) != 0) return false;
  p += 4;
  for (unsigned i = 0; i < 3; ++i) {
    if (*p < '0' || *p > '9') return false;
    std::uint64_t value = 0;
    while (*p >= '0' && *p <= '9') {
      value = value * 10U + static_cast<unsigned>(*p++ - '0');
      if (value > UINT32_MAX) return false;
    }
    values[i] = static_cast<std::uint32_t>(value);
    if (i < 2 && *p++ != ' ') return false;
  }
  return *p == '\0';
}
FLASHMEM void command(usb::TeensyCdcByteStream &stream, std::uint8_t *buffer) {
  state.command[state.command_size] = '\0';
  if (state.running) {
    if (std::strcmp(state.command, "STOP") == 0) state.stop = true;
    return;
  }
  std::uint8_t reply[64]{};
  std::size_t reply_size = 32;
  std::memcpy(reply, "TDERR001", 8);
  if (std::strcmp(state.command, "PROTOCOL") == 0) {
    enabled = false;
    std::memcpy(reply, "TDPROT01", 8);
  } else if (std::strcmp(state.command, "INFO") == 0) {
    reply_size = 64;
    std::memcpy(reply, "TDINFO01", 8);
    static_assert(identity::kBuildId.size() <= 32);
    std::memcpy(reply + 8, identity::kBuildId.data(), identity::kBuildId.size());
    put32(reply + 40, usb::hardwareSerialNumber()); put32(reply + 44, F_CPU_ACTUAL);
    put32(reply + 48, usb_high_speed); put32(reply + 52, 8192);
    put32(reply + 56, 4); put32(reply + 60, 2048);
  } else {
    std::uint32_t values[3]{};
    const bool valid = parseRun(state.command, values);
    const auto mode = values[0], milliseconds = values[1], rate = values[2];
    if (valid && mode >= 1 && mode <= 5 && milliseconds >= 100 &&
        milliseconds <= 30000 && rate <= 60000000U) {
      ++state.run;
      state.mode = mode; state.duration_us = milliseconds * 1000U; state.rate = rate;
      state.sequence = 0; state.bytes = 0; state.calls = 0; state.active_us = 0;
      state.short_writes = 0; state.offset = 0; state.stop = false;
      state.transfer_size = (mode == 1 || mode == 3) ? 4096U : 8192U;
      // Prebuilt synthetic bytes isolate framing/write/USB/host cost from capture.
      // Each payload restarts the same 256-byte ramp; full contents are host-checked.
      const std::uint32_t frame_size = mode == 4 ? 4096U : state.transfer_size;
      for (std::uint32_t base = 0; base < 8192U; base += frame_size) {
        for (std::uint32_t i = kHeader; i < frame_size; ++i)
          buffer[base + i] = static_cast<std::uint8_t>((i - kHeader) & 255U);
      }
      std::memcpy(reply, "TDACK001", 8);
      put32(reply + 8, state.run); put32(reply + 12, mode);
      put32(reply + 16, milliseconds); put32(reply + 20, rate);
      put32(reply + 24, state.transfer_size);
      state.running = true;
    }
  }
  (void)stream.write(reply, reply_size);
  if (state.running) state.started = micros();
}
}  // namespace

FLASHMEM bool active() { return enabled; }

FLASHMEM void service(usb::TeensyCdcByteStream &stream,
                     packet::PacketBufferPrimaryStorage &storage) {
  // Access the complete storage object's byte representation, not past a subarray.
  auto *buffer = reinterpret_cast<std::uint8_t *>(&storage);
  static_assert(sizeof(storage) >= 8192);
  if (!stream.sessionOpen()) {
    state.running = false; state.command_size = 0; return;
  }
  for (unsigned budget = 0; budget < 80 && stream.available() > 0; ++budget) {
    std::uint8_t byte = 0;
    if (stream.read(&byte, 1) != 1) break;
    if (byte == '\n') {
      command(stream, buffer); state.command_size = 0;
    } else if (state.command_size + 1 < sizeof(state.command)) {
      state.command[state.command_size++] = static_cast<char>(byte);
    } else {
      state.command_size = 0;
    }
  }
  if (!state.running) return;
  const auto elapsed = static_cast<std::uint32_t>(micros() - state.started);
  if (state.offset == 0 && (state.stop || elapsed >= state.duration_us)) {
    finish(stream, buffer); return;
  }
  if (state.offset == 0) {
    if (state.rate && state.bytes * 1000000ULL > static_cast<std::uint64_t>(elapsed) * state.rate) return;
    dataHeader(buffer, state.sequence, state.mode == 4 ? 4096U : state.transfer_size);
    if (state.mode == 4) dataHeader(buffer + 4096, state.sequence + 1, 4096);
  }
  const auto started = micros();
  const auto remaining = state.transfer_size - state.offset;
  const auto written = stream.write(buffer + state.offset, remaining);
  state.active_us += static_cast<std::uint32_t>(micros() - started);
  ++state.calls;
  if (written < 0 || static_cast<std::uint32_t>(written) > remaining) {
    state.running = false; return;
  }
  if (static_cast<std::uint32_t>(written) != remaining) ++state.short_writes;
  state.offset += static_cast<std::uint32_t>(written);
  state.bytes += static_cast<std::uint32_t>(written);
  if (state.offset == state.transfer_size) {
    state.offset = 0; state.sequence += state.mode == 4 ? 2U : 1U;
  }
}
}  // namespace thingdaq::usb_throughput
#endif
