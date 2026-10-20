// Reuse portable CDC/clock fakes and the production runtime link surface.
#define main existing_runtime_regressions_main
#include "firmware_runtime_test.cpp"
#undef main
#include <cassert>

namespace {
// Commands are supplied by Python (including generated golden bytes), never
// serialized by the firmware under test. The line wrapper is test-only.
wire::CommandFrame inputCommand(const std::string &hex) {
  wire::CommandFrame frame;
  assert(hex.size() % 2U == 0U && frame.setSize(hex.size() / 2U));
  for (std::size_t i = 0; i < frame.size(); ++i)
    frame.mutableData()[i] = static_cast<std::uint8_t>(std::stoul(hex.substr(i * 2U, 2U), nullptr, 16));
  return frame;
}

void runtimeSession() {
  FakeCdcStream stream;
  stream.max_read_size = 3U;
  stream.max_write_size = 7U;
  packet::OwnedPacketBufferStorage storage;
  FakeTickClock clock;
  app::FirmwareRuntime firmware{stream, storage, clock};
  assert(firmware.begin(12345678U));
  auto pump = [&]() {
    for (unsigned pass = 0; pass < 100000U; ++pass) {
      assert(!firmware.service().internal_error);
      const auto t = firmware.transportSnapshot();
      assert(t.io_errors == 0U);
      if (stream.inputEmpty() && t.pending_rx_bytes == 0U &&
          t.command_queue_depth == 0U && t.response_queue_depth == 0U &&
          !t.command_awaiting_response && !firmware.hasPendingTransmission() &&
          firmware.packetSnapshot().pending_frames == 0U) return;
    }
    assert(false && "runtime drain exceeded bound");
  };
  std::string operation, argument;
  while (std::cin >> operation >> argument) {
    // Queue a command or leave a frame partially transmitted so the next
    // commands exercise production STOP/drain admission, before USB empties.
    if (operation == "Q") {
      stream.appendInput(inputCommand(argument));
      continue;
    }
    if (operation == "A") {
      clock.ticks += std::stoull(argument);
      // Compressed frames need deferred codec visits before first USB write.
      for (unsigned pass = 0; pass < 1000U; ++pass) {
        assert(!firmware.service().internal_error);
        if (firmware.transportSnapshot().active_frame_bytes_sent != 0U) break;
      }
      assert(firmware.packetSnapshot().pending_frames != 0U);
      assert(firmware.transportSnapshot().active_frame_bytes_sent != 0U);
      continue;
    }
    if (operation == "C") stream.appendInput(inputCommand(argument));
    else if (operation == "T") clock.ticks += std::stoull(argument);
    else {
      // Deliberately fill/evict packet pages while CDC accepts no bytes.
      assert(operation == "S");
      stream.available_write_size = 0U;
      for (unsigned i = 0; i < std::stoul(argument); ++i) {
        clock.ticks += 8064U;
        for (unsigned visit = 0; visit < 32U; ++visit)
          assert(!firmware.service().internal_error);
      }
      stream.available_write_size = 4096U;
    }
    pump();
  }
  std::cout.write(reinterpret_cast<const char *>(stream.output.data()),
                  static_cast<std::streamsize>(stream.output.size()));
}

void codecSession() {
  // Controlled producer at the packet boundary. ControlState validates the
  // actual incoming commands; its applied settings select the codec layout.
  // This mode deliberately does not simulate physical acquisition or counters.
  control::ControlState state;
  assert(state.completeBoot(12345678U));
  FakeCdcStream stream;
  stream.max_write_size = 7U;
  packet::OwnedPacketBufferStorage storage;
  packet::PacketBufferPipeline pipeline(storage);
  usb::CdcTransport transport(stream, state.statistics(), &pipeline);
  auto drain = [&]() {
    for (unsigned i = 0; i < 10000U; ++i) {
      pipeline.serviceDeferred(0U);
      pipeline.serviceReadyFrames();
      transport.serviceTransmit();
      if (pipeline.quiescent() && !transport.hasPendingTransmission()) return;
    }
    assert(false && "codec drain exceeded bound");
  };
  wire::IncrementalCommandParser parser;
  std::string operation, argument;
  while (std::cin >> operation >> argument) {
    if (operation == "C") {
      const auto incoming = inputCommand(argument);
      for (std::size_t i = 0; i < incoming.size(); ++i) {
        wire::ParsedCommand command;
        const auto fed = parser.feed({incoming.data() + i, 1U}, command);
        assert(!fed.rejection_ready);
        if (!fed.command_ready) continue;
        wire::ControlFrame response;
        assert(state.dispatch(command.request, response).commandAccepted());
        assert(transport.queueResponse(response));
        const auto events = state.takePendingEvents();
        if (events.has(control::Event::kStartEpoch)) {
          const auto layout = thingdaq::stream_layout::publicV3(
              state.activeSettings().settings, 12U, 12U);
          assert(layout.ok());
          assert(pipeline.startRun(state.runId(), constants::kDefaultChecksumAlgorithm,
              packet::kAllStreamMask, layout.layout) == packet::OperationStatus::kOk);
        }
        if (events.has(control::Event::kStop)) pipeline.stopProduction();
      }
    } else {
      assert(operation == "P" && state.state() == constants::DeviceState::kRunning);
      const unsigned pattern = static_cast<unsigned>(std::stoul(argument));
      assert(pattern < 4U);
      for (auto source : {packet::Stream::kAdc, packet::Stream::kGpio}) {
        const auto begun = pipeline.beginFill(source);
        assert(begun.ok());
        const auto view = pipeline.writablePayload(begun.handle);
        const auto &layout = pipeline.streamLayout(source);
        constexpr std::array<std::uint16_t, 8U> edges{0U,4095U,4095U,0U,0x123U,0xABCU,0x800U,0x7FFU};
        for (unsigned i = 0; i < layout.item_count; ++i) {
          if (source == packet::Stream::kAdc) {
            assert(wire::storeU16(view, i * 4U, edges[(i * 2U) % 8U]));
            assert(wire::storeU16(view, i * 4U + 2U, edges[(i * 2U + 1U) % 8U]));
          } else {
            const auto span = pattern == 0U ? 12U : pattern == 1U ? 1U :
                pattern == 2U ? (layout.item_bytes == 1U ? 3U : 2U) : 6U;
            view.data[i * layout.item_bytes] = static_cast<std::uint8_t>(i / span);
            if (layout.item_bytes == 2U) view.data[i * 2U + 1U] = 0xABU;
          }
        }
        packet::FrameCompletion completion;
        completion.payload_bytes_written = view.size;
        completion.first_sample_ticks = begun.handle.sequence * 96U;
        completion.flags = static_cast<std::uint16_t>((begun.handle.sequence == 0U ? 4U : 0U) |
            (state.activeSettings().settings[1] == 1U ? 1U : 0U));
        assert(pipeline.finishFill(begun.handle, completion).ok());
      }
    }
    drain();
  }
  assert(state.state() != constants::DeviceState::kRunning);
  std::cout.write(reinterpret_cast<const char *>(stream.output.data()),
                  static_cast<std::streamsize>(stream.output.size()));
}
}  // namespace

int main(int argc, char **argv) {
  assert(argc == 2);
  if (std::string(argv[1]) == "runtime") runtimeSession();
  else { assert(std::string(argv[1]) == "codec"); codecSession(); }
  return failures == 0 ? 0 : 1;
}
