#include "control_state.h"
#include "input_experiment_profile.h"
#include "board_config.h"
#include <cassert>

using namespace thingdaq;
int main() {
  static_assert(input_experiment::kReleaseFixed1MHz);
  static_assert(input_experiment::kCpuHz == 450000000U);
  static_assert(board::kAdcDmaActivePipelineDepth == 4U);
  static_assert(board::kAdcDmaRingDepth - board::kAdcDmaActivePipelineDepth == 4U);
  protocol::Configuration defaults{};
  assert(defaults.protocol_version == 2U);
  assert(static_cast<unsigned>(defaults.rate_profile) == 4U);
  control::ControlState state{};
  assert(state.completeBoot(20428100U));
  protocol::ControlFrame response{};
  protocol::Request request{};
  request.protocol_version = 2U;
  request.kind = protocol_v1::CommandKind::kConfigure;
  request.configuration = control::kSyntheticConfiguration;
  for (unsigned mode = 0; mode < 2U; ++mode) {
    request.configuration.aux_bank_mode = static_cast<protocol_v2::AuxBankMode>(mode);
    for (unsigned profile = 0; profile < 5U; ++profile) {
      ++request.request_id;
      request.configuration.rate_profile = static_cast<protocol_v2::RateProfile>(profile);
      const auto result = state.dispatch(request, response);
      assert(result.commandAccepted() == (profile == 4U));
      request.kind = protocol_v1::CommandKind::kStop;
      ++request.request_id;
      assert(state.dispatch(request, response).commandAccepted());
      request.kind = protocol_v1::CommandKind::kConfigure;
    }
  }
  protocol::FrameFields fields{};
  fields.kind = protocol_v1::FrameKind::kInfoRequest;
  fields.request_id = 200U;
  protocol::CommandFrame wire{};
  fields.version = 1U;
  assert(protocol::encodeFrame(fields, {}, wire).ok());
  assert(!protocol::decodeRequest(wire.view(), request).ok());
  fields.version = 2U;
  assert(protocol::encodeFrame(fields, {}, wire).ok());
  assert(protocol::decodeRequest(wire.view(), request).ok());
}
