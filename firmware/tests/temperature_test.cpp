#include "control_state.h"
#include "temperature.h"
#include <cassert>

using namespace thingdaq;

int main() {
  const std::uint32_t calibration = 105U | (1000U << 8U) | (1400U << 20U);
  const auto control = [](std::uint32_t count) { return 6U | (count << 8U); };
  assert(temperature::decode(control(1400), calibration).millidegrees_c == 25000);
  assert(temperature::decode(control(1000), calibration).millidegrees_c == 105000);
  assert(temperature::decode(control(1550), calibration).millidegrees_c == -5000);
  assert(temperature::decode(control(1725), calibration).millidegrees_c == -40000);
  assert(temperature::decode(control(775), calibration).millidegrees_c == 150000);
  assert(temperature::decode(control(1726), calibration).status == temperature::Status::kOutOfRange);
  assert(temperature::decode(control(774), calibration).status == temperature::Status::kOutOfRange);
  assert(temperature::decode(0, calibration).status == temperature::Status::kUnavailable);
  assert(temperature::decode(7, calibration).status == temperature::Status::kUnavailable);
  assert(temperature::decode(2, calibration).status == temperature::Status::kNotReady);
  assert(temperature::decode(6, 0).status == temperature::Status::kInvalidCalibration);
  assert(temperature::decode(6, 105U | (1000U << 8U) | (1000U << 20U)).status ==
         temperature::Status::kInvalidCalibration);
  assert(temperature::decode(control(4095), 150U | (1U << 8U) | (2U << 20U)).status ==
         temperature::Status::kOutOfRange);

  protocol::FrameFields fields{};
  fields.version = 2;
  fields.kind = protocol::kTemperatureRequest;
  fields.request_id = 1;
  protocol::CommandFrame frame{};
  assert(protocol::encodeFrame(fields, {}, frame).ok());
  protocol::Request request{};
  assert(protocol::decodeRequest(frame.view(), request).ok());
  assert(request.kind == protocol::kGetTemperature);
  fields.version = 1;
  assert(!protocol::encodeFrame(fields, {}, frame).ok());
  fields.version = 2;
  std::uint8_t byte = 0;
  assert(!protocol::encodeFrame(fields, {&byte, 1}, frame).ok());

  control::ControlState state{};
  assert(state.completeBoot(20428100));
  protocol::ControlFrame response{};
  control::DispatchReadiness readiness{};
  readiness.temperature = {temperature::Status::kValid, -5000};
  assert(state.dispatch(request, response, readiness).commandAccepted());
  protocol::DecodedFrame decoded{};
  assert(protocol::decodeFrame(response.view(), decoded).ok());
  assert(decoded.header.kind == protocol::kTemperatureResponse);
  assert(decoded.header.request_id == request.request_id);
  std::uint32_t value = 0;
  assert(protocol::loadU32(decoded.payload, 8, value));
  assert(value == static_cast<std::uint32_t>(-5000));
  assert(state.state() == protocol_v1::DeviceState::kIdle);
  // Replay is a correlated typed error, not a state mutation.
  assert(!state.dispatch(request, response, readiness).commandAccepted());
  assert(protocol::decodeFrame(response.view(), decoded).ok());
  assert(decoded.header.kind == protocol::kTemperatureResponse);
  assert(decoded.payload.size == 4);
  ++request.request_id;
  assert(state.dispatch(request, response).commandAccepted());
  assert(protocol::decodeFrame(response.view(), decoded).ok());
  assert(decoded.payload.data[4] == 1);  // Explicit UNAVAILABLE, not 0 C.
  assert(protocol::loadU32(decoded.payload, 8, value) && value == 0);
  readiness.temperature = {temperature::Status::kNotReady, 123};
  assert(!protocol::encodeTemperatureResponse(request, 0, readiness.temperature, response).ok());
  readiness.temperature = {temperature::Status::kValid, 150001};
  assert(!protocol::encodeTemperatureResponse(request, 0, readiness.temperature, response).ok());
  protocol::Request configure{};
  configure.kind = protocol_v1::CommandKind::kConfigure;
  configure.request_id = 100;
  configure.configuration = control::kSyntheticConfiguration;
  assert(state.dispatch(configure, response).commandAccepted());
  request.request_id = 101;
  assert(state.dispatch(request, response).commandAccepted());
  assert(state.state() == protocol_v1::DeviceState::kConfigured);
  configure.kind = protocol_v1::CommandKind::kStart;
  configure.request_id = 102;
  assert(state.dispatch(configure, response).commandAccepted());
  const auto run_id = state.runId();
  request.request_id = 103;
  readiness.temperature = {temperature::Status::kValid, 42500};
  assert(state.dispatch(request, response, readiness).commandAccepted());
  assert(state.state() == protocol_v1::DeviceState::kRunning && state.runId() == run_id);
  assert(protocol::decodeFrame(response.view(), decoded).ok());
  assert(decoded.header.run_id == run_id && decoded.header.request_id == 103);
  assert(protocol::loadU32(decoded.payload, 8, value) && value == 42500);
  return 0;
}
