// Exercise real runtime dispatch/packet/codec/USB code with the existing fakes.
#define main existing_runtime_regressions_main
#include "firmware_runtime_test.cpp"
#undef main
#include <cassert>

int main(int argc, char **argv) {
  assert(argc == 3);
  namespace v3 = thingdaq::protocol_v3;
  const bool auxiliary = std::string(argv[1]) == "16";
  const bool compressed = std::string(argv[2]) == "1";
  FakeCdcStream stream;
  stream.max_read_size = 3U;
  stream.max_write_size = 7U;
  packet::OwnedPacketBufferStorage storage;
  FakeTickClock clock;
  app::FirmwareRuntime firmware{stream, storage, clock};
  assert(firmware.begin(12345678U));
  auto settings = thingdaq::settings::kBuildDefaults;
  settings[v3::kSettingsSourceOffset] = 1U;
  settings[v3::kSettingsAuxBankModeOffset] = auxiliary ? 1U : 0U;
  settings[v3::kSettingsGpioWidthBitsOffset] = auxiliary ? 16U : 8U;
  settings[v3::kSettingsGpioPolicyOffset] = compressed ? 1U : 0U;
  settings[v3::kSettingsAdcPolicyOffset] = compressed ? 1U : 0U;
  std::uint32_t id = 0U;
  auto send = [&](std::uint8_t kind, std::uint8_t version = 3U) {
    wire::FrameFields fields;
    fields.version = version;
    fields.kind = static_cast<constants::FrameKind>(kind);
    fields.request_id = ++id;
    wire::CommandFrame frame;
    wire::ByteView payload{};
    if (kind == 17U) payload = {settings.data(), settings.size()};
    assert(wire::encodeFrame(fields, payload, frame).ok());
    stream.appendInput(frame);
  };
  auto pump = [&]() {
    for (unsigned i = 0; i < 6000U; ++i) {
      const auto report = firmware.service();
      assert(!report.internal_error);
      const auto transport = firmware.transportSnapshot();
      assert(transport.io_errors == 0U);
      if (stream.inputEmpty() && transport.pending_rx_bytes == 0U &&
          transport.command_queue_depth == 0U && transport.response_queue_depth == 0U &&
          !transport.command_awaiting_response && !firmware.hasPendingTransmission() &&
          firmware.packetSnapshot().pending_frames == 0U) return;
    }
    assert(false && "bounded drain failed");
  };
  send(17U); pump();
  send(18U); pump();
  assert(firmware.runId() == 1U && firmware.state() == constants::DeviceState::kRunning);
  // Queries cannot reset a run or change mode.
  send(16U); send(29U); pump();
  for (unsigned i = 0U; i < 4U; ++i) { clock.ticks += 8064U; pump(); }
  send(19U); pump();
  clock.ticks += 32256U;
  for (unsigned i = 0; i < 12U; ++i) assert(!firmware.service().internal_error);
  assert(firmware.hasPendingTransmission());
  send(20U); send(17U); pump(); // CONFIGURE is busy while old wire bytes drain.
  send(19U); pump();
  send(20U); pump(); // idempotent STOP preserves settings/counters
  send(18U); pump(); // no repeated CONFIGURE required
  assert(firmware.runId() == 2U);
  clock.ticks += 32256U; pump();
  send(20U); pump();
  send(19U); pump();
  // The constant-time guard rejects malformed envelopes/prefixes before USB
  // takes ownership, even when a damaged view happens to have a legacy size.
  std::size_t at = 0U;
  while (at < stream.output.size()) {
    wire::ByteView remaining{stream.output.data() + at, stream.output.size() - at};
    std::uint32_t size = 0U;
    assert(wire::loadU32(remaining, 12U, size));
    assert(size <= remaining.size);
    if (remaining.data[5] == 1U || remaining.data[5] == 2U) {
      const wire::ByteView valid{remaining.data, size};
      assert(wire::validV3DataView(valid));
      for (const auto offset : {0U, 5U, 8U, 10U, 11U, 12U, 16U, 28U, 40U, 45U, 46U, 48U, 52U}) {
        std::vector<std::uint8_t> bad(valid.data, valid.data + valid.size);
        bad[offset] ^= 0x80U;
        assert(!wire::validV3DataView({bad.data(), bad.size()}));
      }
    }
    at += size;
  }
  std::cout.write(reinterpret_cast<const char *>(stream.output.data()),
                  static_cast<std::streamsize>(stream.output.size()));
  return failures == 0 ? 0 : 1;
}
