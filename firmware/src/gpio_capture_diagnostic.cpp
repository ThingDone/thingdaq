#include "gpio_capture_diagnostic.h"

#if defined(__IMXRT1062__)
#define TEENSY_DAQ_GPIO_DIAGNOSTIC_COLD_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))
#else
#define TEENSY_DAQ_GPIO_DIAGNOSTIC_COLD_CODE(section_name)
#endif

namespace teensy_daq::gpio_diagnostic {
namespace {

constexpr bool known(MetadataKind kind) {
  return kind == MetadataKind::kAbsent ||
         kind == MetadataKind::kDocumentationOnly ||
         kind == MetadataKind::kMachineReadable;
}

constexpr bool known(DriveSafety safety) {
  return safety == DriveSafety::kUnspecified ||
         safety == DriveSafety::kForbidden ||
         safety == DriveSafety::kExplicitlySafe;
}

constexpr bool known(StimulusKind kind) {
  return kind == StimulusKind::kNone || kind == StimulusKind::kLoopback ||
         kind == StimulusKind::kExternal;
}

void addError(Snapshot &snapshot, Error error) {
  snapshot.hardware_error_flags |= errorBit(error);
}

bool pinsAreSafeInputs(std::uint32_t gpr27, std::uint32_t gpio2_gdir) {
  return (gpr27 & board::kGpio7ToGpio2Gpr27ClearMask) == 0U &&
         (gpio2_gdir & board::kGpio2PsrCaptureMask) == 0U;
}

}  // namespace

TEENSY_DAQ_GPIO_DIAGNOSTIC_COLD_CODE(".flashmem.gpio_diagnostic.policy")
bool fixtureDeclarationValid(const FixtureDeclaration &declaration) {
  if (!known(declaration.metadata_kind) ||
      !known(declaration.drive_safety) ||
      !known(declaration.stimulus_kind)) {
    return false;
  }

  if (declaration.metadata_kind != MetadataKind::kMachineReadable) {
    return declaration.drive_safety != DriveSafety::kExplicitlySafe &&
           declaration.stimulus_kind == StimulusKind::kNone &&
           declaration.stimulus_identity == 0U;
  }

  if (declaration.schema_version == 0U ||
      declaration.fixture_identity == 0U ||
      declaration.declared_teensy_pin_mask != kRequiredTeensyPinMask) {
    return false;
  }
  if (declaration.stimulus_kind != StimulusKind::kNone &&
      declaration.stimulus_identity == 0U) {
    return false;
  }
  return true;
}

TEENSY_DAQ_GPIO_DIAGNOSTIC_COLD_CODE(".flashmem.gpio_diagnostic.plan")
Plan makePlan(const FixtureDeclaration &declaration) {
  Plan result{};
  result.declaration_valid = fixtureDeclarationValid(declaration);
  if (!result.declaration_valid ||
      declaration.metadata_kind != MetadataKind::kMachineReadable) {
    return result;
  }

  result.fixture_identity = declaration.fixture_identity;
  result.stimulus_identity = declaration.stimulus_identity;
  if (declaration.stimulus_kind != StimulusKind::kNone) {
    result.mode = Mode::kFixtureStimulus;
    result.external_stimulus_declared = true;
    return result;
  }
  if (declaration.drive_safety == DriveSafety::kExplicitlySafe) {
    result.mode = Mode::kSelfDrivenSweep;
    result.analysis_sample_limit =
        static_cast<std::uint32_t>(kSweepValueCount) *
        kSweepSamplesPerValue;
    result.value_count = kSweepValueCount;
    result.samples_per_value = kSweepSamplesPerValue;
    result.output_drive_permitted = true;
  }
  return result;
}

TEENSY_DAQ_GPIO_DIAGNOSTIC_COLD_CODE(".flashmem.gpio_diagnostic.runner")
RunResult Runner::run() {
  RunResult result{};
  const Plan selected = makePlan(declaration_);
  Snapshot &snapshot = result.snapshot;
  snapshot.mode = selected.mode;
  snapshot.fixture_identity = selected.fixture_identity;
  snapshot.stimulus_identity = selected.stimulus_identity;
  if (!selected.declaration_valid) {
    addError(snapshot, Error::kFixtureDeclarationInvalid);
  }

  if (!platform_.execute(selected, snapshot)) {
    result.status = RunStatus::kPlatformUnavailable;
    return result;
  }
  result.status = RunStatus::kOk;

  if (snapshot.mode != selected.mode) {
    addError(snapshot, Error::kUnsupportedFixtureMode);
  }
  if (snapshot.output_drive_exercised &&
      !selected.output_drive_permitted) {
    addError(snapshot, Error::kUnexpectedOutputDrive);
  }
  if (!pinsAreSafeInputs(snapshot.registers.gpr27_configured,
                         snapshot.registers.gpio2_gdir_configured)) {
    addError(snapshot, Error::kUnsafeConfiguredDirection);
  }
  snapshot.final_input_safe = pinsAreSafeInputs(
      snapshot.registers.gpr27_after,
      snapshot.registers.gpio2_gdir_after);
  if (!snapshot.final_input_safe) {
    addError(snapshot, Error::kUnsafeInputRestore);
  }

  if (snapshot.dma_capture_exercised &&
      (snapshot.samples_analyzed != selected.analysis_sample_limit ||
       snapshot.complete_samples_retained < snapshot.samples_analyzed ||
       snapshot.dma_samples_captured <
           snapshot.complete_samples_retained)) {
    addError(snapshot, Error::kCountMismatch);
  }
  if (snapshot.mapping_failures != 0U || snapshot.unstable_samples != 0U) {
    addError(snapshot, Error::kMappingMismatch);
  }

  switch (selected.mode) {
    case Mode::kNonDrivingCapture:
      if (snapshot.external_transition_validation_exercised ||
          snapshot.mapping_values_checked != 0U) {
        addError(snapshot, Error::kUnexpectedElectricalClaim);
      }
      break;
    case Mode::kSelfDrivenSweep:
      if (!snapshot.output_drive_exercised ||
          snapshot.mapping_values_checked != kSweepValueCount ||
          snapshot.samples_analyzed !=
              static_cast<std::uint32_t>(kSweepValueCount) *
                  kSweepSamplesPerValue) {
        addError(snapshot, Error::kMappingMismatch);
      }
      break;
    case Mode::kFixtureStimulus:
      if (!selected.external_stimulus_declared ||
          !snapshot.external_transition_validation_exercised) {
        addError(snapshot, Error::kExternalValidationMissing);
      }
      break;
  }
  return result;
}

}  // namespace teensy_daq::gpio_diagnostic

#undef TEENSY_DAQ_GPIO_DIAGNOSTIC_COLD_CODE
