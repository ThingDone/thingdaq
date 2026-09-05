#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "board_config.h"
#include "gpio_raw_capture.h"

namespace thingdaq::gpio_diagnostic {

// Fixture policy is build-time evidence, never a host-selected diagnostic
// option. A remote request therefore cannot authorize output drive.
enum class MetadataKind : std::uint8_t {
  kAbsent = 0U,
  kDocumentationOnly = 1U,
  kMachineReadable = 2U,
};

enum class DriveSafety : std::uint8_t {
  kUnspecified = 0U,
  kForbidden = 1U,
  kExplicitlySafe = 2U,
};

enum class StimulusKind : std::uint8_t {
  kNone = 0U,
  kLoopback = 1U,
  kExternal = 2U,
};

enum class Mode : std::uint8_t {
  kNonDrivingCapture = 0U,
  kSelfDrivenSweep = 1U,
  kFixtureStimulus = 2U,
};

struct FixtureDeclaration {
  MetadataKind metadata_kind = MetadataKind::kAbsent;
  DriveSafety drive_safety = DriveSafety::kUnspecified;
  StimulusKind stimulus_kind = StimulusKind::kNone;
  std::uint8_t schema_version = 0U;
  std::uint64_t declared_teensy_pin_mask = 0U;
  std::uint32_t fixture_identity = 0U;
  std::uint32_t stimulus_identity = 0U;
};

inline constexpr std::uint64_t kRequiredTeensyPinMask =
    (std::uint64_t{1U} << 6U) | (std::uint64_t{1U} << 7U) |
    (std::uint64_t{1U} << 8U) | (std::uint64_t{1U} << 9U) |
    (std::uint64_t{1U} << 10U) | (std::uint64_t{1U} << 11U) |
    (std::uint64_t{1U} << 12U) | (std::uint64_t{1U} << 13U);
inline constexpr std::uint32_t kNonDrivingAnalysisSamples = 256U;
inline constexpr std::uint16_t kSweepValueCount = 256U;
inline constexpr std::uint16_t kSweepSamplesPerValue = 8U;

struct Plan {
  Mode mode = Mode::kNonDrivingCapture;
  std::uint32_t analysis_sample_limit = kNonDrivingAnalysisSamples;
  std::uint16_t value_count = 0U;
  std::uint16_t samples_per_value = 0U;
  std::uint32_t fixture_identity = 0U;
  std::uint32_t stimulus_identity = 0U;
  bool declaration_valid = true;
  bool output_drive_permitted = false;
  bool external_stimulus_declared = false;
};

// Documentation-only or absent metadata is valid but never authorizes drive.
// Machine-readable declarations must identify this exact eight-pin set before
// either a stimulus or an explicitly safe output sweep can be selected.
bool fixtureDeclarationValid(const FixtureDeclaration &declaration);
Plan makePlan(const FixtureDeclaration &declaration);

enum class Error : std::uint32_t {
  kFixtureDeclarationInvalid = 1U << 0U,
  kUnsupportedFixtureMode = 1U << 1U,
  kDwtUnavailable = 1U << 2U,
  kResourceBusy = 1U << 3U,
  kCaptureTimeout = 1U << 4U,
  kCaptureFault = 1U << 5U,
  kNoCompleteBuffer = 1U << 6U,
  kDiagnosticLeaseError = 1U << 7U,
  kCountMismatch = 1U << 8U,
  kUnsafeConfiguredDirection = 1U << 9U,
  kUnsafeInputRestore = 1U << 10U,
  kMappingMismatch = 1U << 11U,
  kUnexpectedOutputDrive = 1U << 12U,
  kExternalValidationMissing = 1U << 13U,
  kUnexpectedElectricalClaim = 1U << 14U,
  kCleanupFailed = 1U << 15U,
};

constexpr std::uint32_t errorBit(Error error) {
  return static_cast<std::uint32_t>(error);
}

struct RegisterEvidence {
  std::uint32_t gpr27_before = 0U;
  std::uint32_t gpr27_configured = 0U;
  std::uint32_t gpr27_after = 0U;
  std::uint32_t gpio2_gdir_before = 0U;
  std::uint32_t gpio2_gdir_configured = 0U;
  std::uint32_t gpio2_gdir_after = 0U;
  std::uint32_t gpio2_psr_before = 0U;
  std::uint32_t gpio2_psr_configured = 0U;
  std::uint32_t gpio2_psr_after = 0U;
  std::uint32_t pit_ldval_configured = 0U;
  std::uint32_t pit_tctrl_configured = 0U;
  std::uint32_t dmamux_chcfg_configured = 0U;
  std::uint32_t dma_erq_configured = 0U;
  std::uint32_t dma_err_final = 0U;
  std::uint16_t tcd_citer_configured = 0U;
  std::uint16_t tcd_biter_configured = 0U;
  std::uint16_t tcd_csr_configured = 0U;
  std::uint8_t edma_priority_configured = 0U;
  std::uint32_t gpr26_before = 0U;
  std::uint32_t gpr26_configured = 0U;
  std::uint32_t gpr26_after = 0U;
  std::uint32_t gpio1_gdir_before = 0U;
  std::uint32_t gpio1_gdir_configured = 0U;
  std::uint32_t gpio1_gdir_after = 0U;
  std::uint32_t gpio1_psr_before = 0U;
  std::uint32_t gpio1_psr_configured = 0U;
  std::uint32_t gpio1_psr_after = 0U;
  std::uint32_t aux_dmamux_chcfg_configured = 0U;
  std::uint32_t aux_dma_erq_configured = 0U;
  std::uint32_t aux_dma_err_final = 0U;
  std::uint16_t aux_tcd_citer_configured = 0U;
  std::uint16_t aux_tcd_biter_configured = 0U;
  std::uint16_t aux_tcd_csr_configured = 0U;
  std::uint8_t aux_edma_priority_configured = 0U;
};

struct Snapshot {
  Mode mode = Mode::kNonDrivingCapture;
  std::uint32_t fixture_identity = 0U;
  std::uint32_t stimulus_identity = 0U;
  std::uint32_t hardware_error_flags = 0U;
  std::uint32_t dwt_counter_hz = 0U;
  std::uint32_t dwt_elapsed_cycles = 0U;
  std::uint64_t dma_samples_captured = 0U;
  std::uint32_t complete_samples_retained = 0U;
  std::uint32_t samples_analyzed = 0U;
  std::uint32_t stopped_partial_samples = 0U;
  std::uint32_t raw_word_and = 0U;
  std::uint32_t raw_word_or = 0U;
  std::uint32_t observed_transitions = 0U;
  std::uint16_t mapping_values_checked = 0U;
  std::uint16_t mapping_failures = 0U;
  std::uint16_t unstable_samples = 0U;
  std::uint8_t packed_value_and = 0U;
  std::uint8_t packed_value_or = 0U;
  std::uint8_t first_packed_value = 0U;
  std::uint8_t last_packed_value = 0U;
  RegisterEvidence registers{};
  bool dma_capture_exercised = false;
  bool packed_observation_exercised = false;
  bool output_drive_exercised = false;
  bool external_transition_validation_exercised = false;
  bool final_input_safe = false;
  bool auxiliary_capture = false;
  bool aux_electrically_unstimulated = false;
  bool aux_external_transition_checks_run = false;
  std::uint32_t configured_rate_hz = protocol_v1::kGpioSampleRateHz;
  std::uint32_t aux_hardware_error_flags = 0U;
  std::uint64_t aux_dma_samples_captured = 0U;
  std::uint32_t aux_complete_samples_retained = 0U;
  std::uint32_t aux_samples_analyzed = 0U;
  std::uint32_t aux_stopped_partial_samples = 0U;
  std::uint32_t aux_raw_word_and = 0U;
  std::uint32_t aux_raw_word_or = 0U;
  std::uint32_t aux_observed_transitions = 0U;
  std::uint8_t aux_packed_value_and = 0U;
  std::uint8_t aux_packed_value_or = 0U;
  std::uint8_t aux_first_packed_value = 0U;
  std::uint8_t aux_last_packed_value = 0U;
  std::array<std::uint32_t, 2U> cache_dma_discards{};
  std::array<std::uint32_t, 2U> cache_cpu_invalidations{};
};

class Platform {
 public:
  virtual ~Platform() = default;
  virtual bool execute(const Plan &plan, Snapshot &snapshot) = 0;
  virtual bool executeAuxiliary(const Plan &, Snapshot &) { return false; }
};

enum class RunStatus : std::uint8_t {
  kOk,
  kPlatformUnavailable,
};

struct RunResult {
  RunStatus status = RunStatus::kPlatformUnavailable;
  Snapshot snapshot{};

  constexpr bool ok() const { return status == RunStatus::kOk; }
};

class Runner {
 public:
  constexpr Runner(FixtureDeclaration declaration, Platform &platform)
      : declaration_(declaration), platform_(platform) {}

  RunResult run();
  RunResult runAuxiliary();
  Plan plan() const { return makePlan(declaration_); }
  FixtureDeclaration declaration() const { return declaration_; }

 private:
  FixtureDeclaration declaration_{};
  Platform &platform_;
};

static_assert(kRequiredTeensyPinMask == 0x0000000000003FC0ULL);
static_assert(kNonDrivingAnalysisSamples <=
              gpio_capture::kRawWordDiagnosticMaxSamples);
static_assert(kSweepValueCount == 256U);
static_assert(kSweepSamplesPerValue > 1U);
static_assert(board::kGpio2PsrCaptureMask == 0x00030C0FU);

}  // namespace thingdaq::gpio_diagnostic
