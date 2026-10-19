#include <cassert>
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

#include "control_state.h"

namespace wire = thingdaq::protocol;
namespace v1 = thingdaq::protocol_v1;
namespace v3 = thingdaq::protocol_v3;
namespace settings = thingdaq::settings;

class FakeApplication final : public settings::Application {
 public:
  settings::Record defaults() const override {
    return settings::kBoardDefaults;
  }
  bool supports(const settings::Record& value) const override {
    return settings::boardSupports(value);
  }
  bool apply(const settings::Record& value,
             settings::Applied& readback) override {
    ++calls;
    if (fail) return false;
    readback = {value,
                settings::clocksFor(value[v3::kSettingsCpuProfileOffset])};
    if (mismatch) readback.clocks[4] ^= 1U;
    return true;
  }
  unsigned calls = 0U;
  bool fail = false;
  bool mismatch = false;
};

int main(int argc, char** argv) {
  const std::string mode = argc > 1 ? argv[1] : "fixed";
  if (mode == "validate") {
    const std::vector<std::uint8_t> bytes(
        std::istreambuf_iterator<char>(std::cin), {});
    wire::DecodedFrame decoded{};
    return static_cast<int>(
        wire::decodeFrame({bytes.data(), bytes.size()}, decoded).error);
  }
  if (mode == "serialize-start") {
    wire::Request request{};
    request.protocol_version = 3U;
    request.kind = v1::CommandKind::kStart;
    request.request_id = 3U;
    wire::ControlFrame response;
    const settings::Applied applied{settings::kBoardDefaults, settings::clocksFor(1U)};
    assert(wire::encodeV3SettingsResponse(request, 1U, applied, response).ok());
    std::cout.write(reinterpret_cast<const char *>(response.data()),
                    static_cast<std::streamsize>(response.size()));
    return 0;
  }
  FakeApplication fake;
  fake.fail = mode == "fail";
  fake.mismatch = mode == "mismatch";
  settings::Application& app =
      mode == "fixed" || mode == "running" || mode == "draining"
          ? static_cast<settings::Application&>(
                settings::kFixedBuildApplication)
          : fake;
  thingdaq::control::ControlState control(app);
  assert(control.completeBoot(12345678U));
  wire::ControlFrame response;
  if (mode == "running" || mode == "draining") {
    wire::Request config{};
    config.protocol_version = 2U;
    config.kind = v1::CommandKind::kConfigure;
    config.request_id = 9001U;
    config.configuration = thingdaq::control::kSyntheticConfiguration;
    config.configuration.protocol_version = 2U;
    config.configuration.rate_profile =
        thingdaq::protocol_v2::RateProfile::kAdc1mhzGpio1mhz;
    assert(control.dispatch(config, response).commandAccepted());
    config.kind = v1::CommandKind::kStart;
    config.request_id = 9002U;
    assert(control.dispatch(config, response).commandAccepted());
    control.takePendingEvents();
    if (mode == "draining") {
      config.kind = v1::CommandKind::kStop;
      config.request_id = 9003U;
      assert(control.dispatch(config, response).commandAccepted());
      control.takePendingEvents();
    }
  }
  thingdaq::stats::DataPathProgress progress{};
  progress.adc.frames_generated = 9U;
  progress.adc.frames_dropped = 2U;
  progress.adc.items_generated = 1012U;
  progress.adc.items_dropped = 4U;
  control.statistics().publishDataPath(progress);
  const auto generation = control.statistics().generation();
  const auto initial_state = control.state();
  const auto initial_run = control.runId();
  wire::IncrementalCommandParser parser;
  char byte = 0;
  while (std::cin.get(byte)) {
    const auto input = static_cast<std::uint8_t>(byte);
    wire::ParsedCommand command{};
    const auto fed = parser.feed({&input, 1U}, command);
    if (!fed.command_ready && !fed.rejection_ready) continue;
    if (command.rejected()) {
      assert(wire::encodeRejectedFrameResponse(
                 command.rejected_request_id, command.rejected_kind,
                 command.rejected_version, command.rejection_error, response,
                 control.runId())
                 .ok());
    } else {
      thingdaq::control::DispatchReadiness ready{};
      if (mode == "draining") {
        ready.pending_frames = 3U;
        ready.configuration_ready = false;
        ready.start_ready = false;
      }
      const auto mode_before = control.negotiatedVersion();
      const auto calls_before = fake.calls;
      assert(control.dispatch(command.request, response, ready).responseReady());
      if (command.request.kind != v1::CommandKind::kConfigure) {
        assert(control.negotiatedVersion() == mode_before);
        assert(fake.calls == calls_before);
      }
      assert(control.state() == initial_state);
      assert(control.runId() == initial_run);
      assert(control.statistics().generation() == generation);
      assert(control.statistics().snapshot().data_path.adc.items_generated ==
             1012U);
      assert(control.takePendingEvents().mask == 0U);
    }
    std::cout.write(reinterpret_cast<const char*>(response.data()),
                    static_cast<std::streamsize>(response.size()));
  }
  return 0;
}
