#include <cstdint>
#include <iostream>
#include <string>

#include "gpio_capture_diagnostic.h"
#include "gpio_capture_diagnostic_teensy.h"

namespace {

namespace diagnostic = thingdaq::gpio_diagnostic;
namespace board = thingdaq::board;
namespace constants = thingdaq::protocol_v1;

int failures = 0;

void expect(bool condition, const std::string &message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

constexpr std::uint32_t diagnosticErrorBit(diagnostic::Error error) {
  return static_cast<std::uint32_t>(error);
}

class FakePlatform final : public diagnostic::Platform {
 public:
  bool available = true;
  bool claim_output_drive = false;
  bool claim_external_validation = false;
  bool unsafe_configured = false;
  bool unsafe_after = false;
  bool omit_capture = false;
  std::uint32_t calls = 0U;
  diagnostic::Plan observed{};

  bool execute(const diagnostic::Plan &plan,
               diagnostic::Snapshot &snapshot) override {
    ++calls;
    observed = plan;
    if (!available) {
      return false;
    }

    snapshot.mode = plan.mode;
    snapshot.fixture_identity = plan.fixture_identity;
    snapshot.stimulus_identity = plan.stimulus_identity;
    snapshot.registers.gpr27_configured =
        unsafe_configured ? board::kGpio7ToGpio2Gpr27ClearMask : 0U;
    snapshot.registers.gpio2_gdir_configured =
        unsafe_configured ? board::kGpio2PsrCaptureMask : 0U;
    snapshot.registers.gpr27_after =
        unsafe_after ? board::kGpio7ToGpio2Gpr27ClearMask : 0U;
    snapshot.registers.gpio2_gdir_after =
        unsafe_after ? board::kGpio2PsrCaptureMask : 0U;
    snapshot.output_drive_exercised = claim_output_drive;
    snapshot.external_transition_validation_exercised =
        claim_external_validation;
    if (!omit_capture) {
      snapshot.dma_capture_exercised = true;
      snapshot.packed_observation_exercised = true;
      snapshot.dma_samples_captured = constants::kGpioSamplesPerFrame + 7U;
      snapshot.complete_samples_retained =
          static_cast<std::uint32_t>(constants::kGpioSamplesPerFrame);
      snapshot.samples_analyzed = plan.analysis_sample_limit;
    }
    if (plan.mode == diagnostic::Mode::kSelfDrivenSweep) {
      snapshot.mapping_values_checked = diagnostic::kSweepValueCount;
      snapshot.samples_analyzed =
          static_cast<std::uint32_t>(diagnostic::kSweepValueCount) *
          diagnostic::kSweepSamplesPerValue;
    }
    return true;
  }
};

diagnostic::FixtureDeclaration machineDeclaration() {
  diagnostic::FixtureDeclaration result{};
  result.metadata_kind = diagnostic::MetadataKind::kMachineReadable;
  result.schema_version = 1U;
  result.declared_teensy_pin_mask = diagnostic::kRequiredTeensyPinMask;
  result.fixture_identity = 0x10203040U;
  return result;
}

void testFailClosedPolicySelection() {
  const diagnostic::Plan registered =
      diagnostic::makePlan(diagnostic::kRegisteredTeensyFixture);
  expect(registered.declaration_valid &&
             registered.mode == diagnostic::Mode::kNonDrivingCapture &&
             !registered.output_drive_permitted &&
             !registered.external_stimulus_declared,
         "the audited Port 15 declaration is compile-time non-driving");

  diagnostic::FixtureDeclaration declaration{};
  diagnostic::Plan plan = diagnostic::makePlan(declaration);
  expect(plan.declaration_valid &&
             plan.mode == diagnostic::Mode::kNonDrivingCapture &&
             !plan.output_drive_permitted &&
             !plan.external_stimulus_declared,
         "absent fixture metadata selects non-driving capture");

  declaration.metadata_kind = diagnostic::MetadataKind::kDocumentationOnly;
  plan = diagnostic::makePlan(declaration);
  expect(plan.declaration_valid &&
             plan.mode == diagnostic::Mode::kNonDrivingCapture &&
             plan.fixture_identity == 0U,
         "prose-only fixture documentation cannot authorize output");

  declaration = machineDeclaration();
  declaration.drive_safety = diagnostic::DriveSafety::kForbidden;
  plan = diagnostic::makePlan(declaration);
  expect(plan.declaration_valid &&
             plan.mode == diagnostic::Mode::kNonDrivingCapture &&
             !plan.output_drive_permitted,
         "an explicit fixture prohibition remains non-driving");

  declaration.drive_safety = diagnostic::DriveSafety::kExplicitlySafe;
  plan = diagnostic::makePlan(declaration);
  expect(plan.declaration_valid &&
             plan.mode == diagnostic::Mode::kSelfDrivenSweep &&
             plan.output_drive_permitted &&
             plan.value_count == 256U && plan.samples_per_value == 8U &&
             plan.analysis_sample_limit == 2048U,
         "only an exact machine declaration admits the 256-value sweep");

  declaration = machineDeclaration();
  declaration.stimulus_kind = diagnostic::StimulusKind::kLoopback;
  declaration.stimulus_identity = 0x55667788U;
  plan = diagnostic::makePlan(declaration);
  expect(plan.declaration_valid &&
             plan.mode == diagnostic::Mode::kFixtureStimulus &&
             plan.external_stimulus_declared &&
             !plan.output_drive_permitted &&
             plan.stimulus_identity == 0x55667788U,
         "a declared loopback is consumed without driving capture pins");

  declaration.declared_teensy_pin_mask &= ~(std::uint64_t{1U} << 13U);
  plan = diagnostic::makePlan(declaration);
  expect(!plan.declaration_valid &&
             plan.mode == diagnostic::Mode::kNonDrivingCapture &&
             !plan.output_drive_permitted &&
             plan.fixture_identity == 0U,
         "a partial or malformed declaration fails closed");
}

void testNonDrivingEvidenceAndCoverageBoundary() {
  diagnostic::FixtureDeclaration declaration{};
  declaration.metadata_kind = diagnostic::MetadataKind::kDocumentationOnly;
  FakePlatform platform{};
  diagnostic::Runner runner{declaration, platform};
  diagnostic::RunResult result = runner.run();
  expect(result.ok() && platform.calls == 1U &&
             platform.observed.mode ==
                 diagnostic::Mode::kNonDrivingCapture &&
             result.snapshot.dma_capture_exercised &&
             result.snapshot.packed_observation_exercised &&
             !result.snapshot.output_drive_exercised &&
             !result.snapshot.external_transition_validation_exercised &&
             result.snapshot.mapping_values_checked == 0U &&
             result.snapshot.samples_analyzed == 256U &&
             result.snapshot.final_input_safe &&
             result.snapshot.hardware_error_flags == 0U,
         "healthy non-driving mode reports capture evidence without an electrical claim");

  platform.claim_output_drive = true;
  result = runner.run();
  expect((result.snapshot.hardware_error_flags &
          diagnosticErrorBit(diagnostic::Error::kUnexpectedOutputDrive)) != 0U,
         "prose-only metadata rejects a platform output-drive claim");

  platform.claim_output_drive = false;
  platform.claim_external_validation = true;
  result = runner.run();
  expect((result.snapshot.hardware_error_flags &
          diagnosticErrorBit(
              diagnostic::Error::kUnexpectedElectricalClaim)) != 0U,
         "floating input observations cannot become external validation");
}

void testSafetyCountAndAvailabilityClassification() {
  diagnostic::FixtureDeclaration declaration{};
  FakePlatform platform{};
  diagnostic::Runner runner{declaration, platform};

  platform.unsafe_configured = true;
  diagnostic::RunResult result = runner.run();
  expect((result.snapshot.hardware_error_flags &
          diagnosticErrorBit(diagnostic::Error::kUnsafeConfiguredDirection)) !=
              0U,
         "configured direction evidence must prove all D6-D13 GPIO2 bits are inputs");

  platform.unsafe_configured = false;
  platform.unsafe_after = true;
  result = runner.run();
  expect(!result.snapshot.final_input_safe &&
             (result.snapshot.hardware_error_flags &
              diagnosticErrorBit(diagnostic::Error::kUnsafeInputRestore)) !=
                 0U,
         "return to IDLE fails closed when any capture direction bit is output");

  platform.unsafe_after = false;
  platform.omit_capture = true;
  result = runner.run();
  expect(result.ok() && !result.snapshot.dma_capture_exercised &&
             result.snapshot.hardware_error_flags == 0U,
         "an unexercised diagnostic does not fabricate capture counts");

  diagnostic::FixtureDeclaration malformed = machineDeclaration();
  malformed.stimulus_kind = diagnostic::StimulusKind::kExternal;
  diagnostic::Runner malformed_runner{malformed, platform};
  result = malformed_runner.run();
  expect((result.snapshot.hardware_error_flags &
          diagnosticErrorBit(
              diagnostic::Error::kFixtureDeclarationInvalid)) != 0U &&
             platform.observed.mode ==
                 diagnostic::Mode::kNonDrivingCapture,
         "invalid machine metadata is visible while the hardware path stays non-driving");

  platform.available = false;
  result = runner.run();
  expect(result.status == diagnostic::RunStatus::kPlatformUnavailable,
         "an unavailable adapter returns no fabricated target evidence");
}

}  // namespace

int main() {
  testFailClosedPolicySelection();
  testNonDrivingEvidenceAndCoverageBoundary();
  testSafetyCountAndAvailabilityClassification();
  if (failures != 0) {
    std::cerr << failures << " GPIO capture diagnostic assertion(s) failed\n";
    return 1;
  }
  std::cout << "GPIO capture diagnostic tests passed\n";
  return 0;
}
