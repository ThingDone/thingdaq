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
    hardware = {value, settings::clocksFor(value[v3::kSettingsCpuProfileOffset])};
    if (fail_rollback) return false;
    if (fail) { fail = false; return false; }
    readback = {value,
                settings::clocksFor(value[v3::kSettingsCpuProfileOffset])};
    if (mismatch) { mismatch = false; readback.clocks[4] ^= 1U; }
    return true;
  }
  settings::Applied hardware{settings::kBoardDefaults, settings::clocksFor(1U)};
  bool fail_rollback = false;
  unsigned calls = 0U;
  bool fail = false;
  bool mismatch = false;
};

void transactions() {
  using namespace thingdaq;
  FakeApplication app;
  control::ControlState state(app);
  assert(state.completeBoot(12345678U));
  wire::ControlFrame response;
  wire::Request request{};
  request.protocol_version = 3U;
  request.kind = v1::CommandKind::kConfigure;
  request.settings = settings::record(v3::kSelectableConfigurations[59]);
  request.request_id = 1U;
  auto dispatch = [&](control::DispatchReadiness ready = {}) {
    return state.dispatch(request, response, ready);
  };
  for (unsigned blocked = 0; blocked < 2; ++blocked) {
    control::DispatchReadiness ready{};
    ready.configuration_ready = blocked != 0U;
    ready.pending_frames = blocked == 1U ? 1U : 0U;
    assert(dispatch(ready).command_error == v1::ErrorCode::kBusy);
    assert(app.calls == 0U && state.negotiatedVersion() == 0U);
    ++request.request_id;
  }
  assert(dispatch().commandAccepted());
  const auto saved = state.activeSettings();
  const auto calls = app.calls;
  assert(dispatch().command_error == v1::ErrorCode::kInvalidRequestId);
  assert(app.calls == calls);
  request.settings = settings::kBoardDefaults;
  for (unsigned failure = 0; failure < 2; ++failure) {
    ++request.request_id;
    app.fail = failure == 0U;
    app.mismatch = failure == 1U;
    const auto before = app.calls;
    assert(dispatch().command_error == v1::ErrorCode::kInternalError);
    assert(app.calls == before + 2U);
    assert(app.hardware.settings == saved.settings && app.hardware.clocks == saved.clocks);
    assert(state.activeSettings().settings == saved.settings);
    assert(state.negotiatedVersion() == 3U && state.runId() == 0U);
  }
  // Neither version of discovery selects a session or touches hardware.
  for (auto version : {2U, 3U}) {
    request.protocol_version = static_cast<std::uint8_t>(version);
    request.kind = v1::CommandKind::kInfo;
    ++request.request_id;
    assert(dispatch().commandAccepted());
    assert(state.negotiatedVersion() == 3U);
  }
  request.protocol_version = 2U;
  request.kind = v1::CommandKind::kStart;
  ++request.request_id;
  assert(dispatch().command_error == v1::ErrorCode::kUnsupportedConfiguration);
  request.kind = v1::CommandKind::kConfigure;
  request.configuration = control::kSyntheticConfiguration;
  request.configuration.protocol_version = 2U;
  request.configuration.aux_bank_mode = protocol_v2::AuxBankMode::kInput;
  request.configuration.rate_profile = protocol_v2::RateProfile::kAdc1mhzGpio1mhz;
  ++request.request_id;
  assert(dispatch().commandAccepted());
  assert(state.negotiatedVersion() == 2U && state.appliedConfiguration().legacy_v2);
  assert(state.activeSettings().settings[v3::kSettingsGpioPolicyOffset] == 0U);
  assert(state.activeSettings().settings[v3::kSettingsAdcPolicyOffset] == 0U);
  assert(state.activeSettings().settings[v3::kSettingsCpuProfileOffset] == settings::kBuildCpuProfile);
  request.kind = v1::CommandKind::kStart;
  ++request.request_id;
  assert(dispatch().commandAccepted());
  const auto start_id = request.request_id;
  assert(state.runId() == 1U);
  assert(dispatch().command_error == v1::ErrorCode::kInvalidRequestId);
  state.takePendingEvents();
  request.protocol_version = 3U;
  request.kind = v1::CommandKind::kConfigure;
  ++request.request_id;
  assert(dispatch().command_error == v1::ErrorCode::kInvalidState);
  request.kind = v1::CommandKind::kStop;
  ++request.request_id;
  assert(dispatch().command_error == v1::ErrorCode::kInvalidState);
  request.kind = v1::CommandKind::kInfo;
  ++request.request_id;
  assert(dispatch().commandAccepted());
  assert(state.state() == v1::DeviceState::kRunning && state.runId() == 1U);
  request.protocol_version = 2U;
  request.kind = v1::CommandKind::kStop;
  ++request.request_id;
  assert(dispatch().commandAccepted());
  request.protocol_version = 3U;
  request.kind = v1::CommandKind::kConfigure;
  ++request.request_id;
  assert(dispatch().command_error == v1::ErrorCode::kBusy); // unconsumed STOP
  state.takePendingEvents();
  ++request.request_id;
  control::DispatchReadiness drain{};
  drain.pending_frames = 1U;
  assert(dispatch(drain).command_error == v1::ErrorCode::kBusy);
  ++request.request_id;
  assert(dispatch().commandAccepted());
  request.protocol_version = 2U;
  request.kind = v1::CommandKind::kStart;
  request.request_id = start_id;
  assert(dispatch().command_error == v1::ErrorCode::kInvalidRequestId);
  assert(state.runId() == 1U && state.negotiatedVersion() == 3U);
  // Failed rollback latches unknown hardware; successful CONFIGURE repairs it.
  state.beginHostSession();
  request.protocol_version = 3U;
  request.kind = v1::CommandKind::kConfigure;
  request.request_id = 1U;
  app.fail_rollback = true;
  assert(dispatch().command_error == v1::ErrorCode::kInternalError);
  request.kind = static_cast<v1::CommandKind>(v3::CommandKind::kGetSettings);
  ++request.request_id;
  assert(dispatch().command_error == v1::ErrorCode::kInternalError);
  app.fail_rollback = false;
  request.kind = v1::CommandKind::kConfigure;
  ++request.request_id;
  assert(dispatch().commandAccepted());
  assert(state.takePendingEvents().mask == 0U);
}

int main(int argc, char** argv) {
  const std::string mode = argc > 1 ? argv[1] : "fixed";
  if (mode == "transactions") { transactions(); return 0; }
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
