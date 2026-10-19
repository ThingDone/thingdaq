// Reuse the runtime fake transport, clock and full portable link surface.
#define main existing_runtime_regressions_main
#include "firmware_runtime_test.cpp"
#undef main
#include <cassert>

int main(int argc, char **argv) {
  assert(argc == 2);
  const bool auxiliary = std::string(argv[1]) == "16";
  namespace v2 = thingdaq::protocol_v2;
  namespace v3 = thingdaq::protocol_v3;
  FakeCdcStream stream;
  stream.max_read_size = 3U;
  stream.max_write_size = 7U;
  packet::OwnedPacketBufferStorage storage;
  FakeTickClock clock;
  app::FirmwareRuntime firmware{stream, storage, clock};
  assert(firmware.begin(12345678U));
  std::uint32_t id = 0U;
  auto send = [&](std::uint8_t version, std::uint8_t kind) {
    wire::FrameFields fields;
    fields.version = version;
    fields.kind = static_cast<constants::FrameKind>(kind);
    fields.request_id = ++id;
    wire::CommandFrame frame;
    std::array<std::uint8_t, 16U> legacy{};
    const auto &defaults = thingdaq::settings::kBuildDefaults;
    wire::ByteView payload{};
    if (kind == 17U && version == 2U) {
      legacy[0] = 3U; legacy[1] = 1U; legacy[2] = 1U;
      legacy[3] = auxiliary ? 1U : 0U;
      wire::storeU32({legacy.data(), legacy.size()}, 4U, 4096U);
      wire::storeU32({legacy.data(), legacy.size()}, 8U, 1000000U);
      wire::storeU32({legacy.data(), legacy.size()}, 12U, 1000000U);
      payload = {legacy.data(), legacy.size()};
    } else if (kind == 17U) payload = {defaults.data(), defaults.size()};
    assert(wire::encodeFrame(fields, payload, frame).ok());
    stream.appendInput(frame);
  };
  auto pump = [&]() {
    for (unsigned i = 0; i < 5000U; ++i) {
      const auto report = firmware.service();
      assert(!report.internal_error);
      const auto transport = firmware.transportSnapshot();
      if (stream.inputEmpty() && transport.pending_rx_bytes == 0U &&
          transport.command_queue_depth == 0U && transport.response_queue_depth == 0U &&
          !transport.command_awaiting_response && !firmware.hasPendingTransmission()) return;
    }
    assert(false && "bounded drain failed");
  };
  send(3U, 17U); pump();                    // explicit v3 settings
  send(2U, 16U); pump();                    // discovery does not switch mode
  send(2U, 18U); pump();                    // wrong-mode START rejected
  assert(firmware.runId() == 0U);
  send(2U, 17U); send(2U, 18U); pump();      // explicit legacy session
  assert(firmware.runId() == 1U && firmware.state() == constants::DeviceState::kRunning);
  send(3U, 16U); send(2U, 16U); send(2U, 19U); pump();
  clock.ticks = 32384U;
  for (unsigned i = 0; i < 12U; ++i) assert(!firmware.service().internal_error);
  assert(firmware.hasPendingTransmission());
  send(2U, 20U); send(3U, 17U); send(3U, 19U); pump();
  assert(firmware.state() == constants::DeviceState::kIdle);
  send(3U, 17U); pump();                    // drained mode switch now succeeds
  send(2U, 16U); pump();                    // query again cannot switch back
  send(2U, 17U); send(2U, 18U); pump();
  assert(firmware.runId() == 2U);
  clock.ticks += 32384U;
  for (unsigned i = 0; i < 12U; ++i) assert(!firmware.service().internal_error);
  send(2U, 20U); pump();
  send(2U, 19U); pump();
  // Preserve release rejection of v1 CONFIGURE (through the real parser).
  stream.appendInput(configureRequest(++id)); pump();
  std::cout.write(reinterpret_cast<const char *>(stream.output.data()),
                  static_cast<std::streamsize>(stream.output.size()));
  return failures == 0 ? 0 : 1;
}
