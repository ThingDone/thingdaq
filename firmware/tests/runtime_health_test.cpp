#include "control_state.h"
#include "runtime_health.h"
#include <array>
#include <cassert>

using namespace thingdaq;

int main() {
  std::array<std::uint32_t, 16> stack{};
  stack.fill(health::kStackCanary);
  auto remaining = health::untouchedWords(stack.data(), stack.size());
  assert(remaining == 16);
  stack[11] = 0;
  remaining = health::untouchedWords(stack.data(), remaining);
  assert(remaining == 11);
  stack[11] = health::kStackCanary;
  assert(health::untouchedWords(stack.data(), remaining) == 11);
  stack[0] = 0;
  assert(health::untouchedWords(stack.data(), remaining) == 0);
  assert(health::untouchedWords(nullptr, 0) == 0);

  protocol::FrameFields fields{};
  fields.version = 2;
  fields.kind = protocol::kRuntimeHealthRequest;
  fields.request_id = 1;
  protocol::CommandFrame frame{};
  assert(protocol::encodeFrame(fields, {}, frame).ok());
  protocol::Request request{};
  assert(protocol::decodeRequest(frame.view(), request).ok());
  assert(request.kind == protocol::kGetRuntimeHealth);
  fields.version = 1;
  assert(!protocol::encodeFrame(fields, {}, frame).ok());
  fields.version = 2;
  const std::uint8_t byte = 0;
  assert(!protocol::encodeFrame(fields, {&byte, 1}, frame).ok());

  control::ControlState state{};
  assert(state.completeBoot(20428100));
  protocol::ControlFrame response{};
  control::DispatchReadiness readiness{};
  readiness.runtime_health = {3, 34000, 28000, 6000, 16, 4000};
  assert(state.dispatch(request, response, readiness).commandAccepted());
  protocol::DecodedFrame decoded{};
  assert(protocol::decodeFrame(response.view(), decoded).ok());
  assert(decoded.header.kind == protocol::kRuntimeHealthResponse);
  assert(decoded.header.request_id == request.request_id);
  std::uint32_t value = 0;
  assert(protocol::loadU32(decoded.payload, 12, value) && value == 28000);
  assert(protocol::loadU32(decoded.payload, 20, value) && value == 16);
  assert(!state.dispatch(request, response, readiness).commandAccepted());
  assert(protocol::decodeFrame(response.view(), decoded).ok());
  assert(decoded.header.kind == protocol::kRuntimeHealthResponse);
  assert(decoded.payload.size == 4);
  ++request.request_id;
  assert(state.dispatch(request, response).commandAccepted());
  assert(protocol::decodeFrame(response.view(), decoded).ok());
  assert(protocol::loadU32(decoded.payload, 4, value) && value == 0);
  for (const auto bad : std::array<health::Reading, 5>{
           health::Reading{4, 0, 0, 0, 0, 0},
           health::Reading{1, 10, 11, 0, 0, 0},
           health::Reading{1, 10, 5, 4, 0, 0},
           health::Reading{0, 10, 5, 5, 0, 0},
           health::Reading{2, 0, 0, 0, 0, 0}}) {
    assert(!protocol::encodeRuntimeHealthResponse(request, 0, bad, response).ok());
  }
  protocol::Request configure{};
  configure.kind = protocol_v1::CommandKind::kConfigure;
  configure.request_id = 100;
  configure.configuration = control::kSyntheticConfiguration;
  assert(state.dispatch(configure, response).commandAccepted());
  request.request_id = 101;
  assert(state.dispatch(request, response, readiness).commandAccepted());
  assert(state.state() == protocol_v1::DeviceState::kConfigured);
  configure.kind = protocol_v1::CommandKind::kStart;
  configure.request_id = 102;
  assert(state.dispatch(configure, response).commandAccepted());
  const auto run_id = state.runId();
  request.request_id = 103;
  assert(state.dispatch(request, response, readiness).commandAccepted());
  assert(state.state() == protocol_v1::DeviceState::kRunning && state.runId() == run_id);
  assert(protocol::decodeFrame(response.view(), decoded).ok());
  assert(decoded.header.run_id == run_id && decoded.header.request_id == 103);
  assert(protocol::loadU32(decoded.payload, 12, value) && value == 28000);
}
