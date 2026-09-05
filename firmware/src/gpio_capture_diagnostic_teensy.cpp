#include "input_experiment_profile.h"

#include "gpio_capture_diagnostic_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <cstddef>
#include <cstdint>
#include <limits>

#include <core_pins.h>
#include <imxrt.h>

#include "gpio_batch_packer.h"
#include "gpio_dual_bank_capture_teensy.h"
#include "gpio_dual_bank_packer.h"
#include "gpio_raw_capture_teensy.h"

#define THINGDAQ_GPIO_DIAGNOSTIC_TARGET_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace thingdaq::gpio_diagnostic {
namespace {

constexpr std::uint32_t kDiagnosticTimeoutCycles =
    input_experiment::kCpuHz / 100U;

void forceSafeInputs() {
  gpio_capture::selectStandardGpioInputs(IOMUXC_GPR_GPR27, GPIO2_GDIR);
  __asm__ volatile("dsb\n\tisb" : : : "memory");
}

void addError(Snapshot &snapshot, Error error) {
  snapshot.hardware_error_flags |= errorBit(error);
}

void recordBefore(const gpio_capture::HardwareSnapshot &source,
                  Snapshot &destination) {
  destination.registers.gpr27_before = source.gpr27;
  destination.registers.gpio2_gdir_before = source.gpio2_gdir;
  destination.registers.gpio2_psr_before = source.gpio2_psr;
}

void recordConfigured(const gpio_capture::HardwareSnapshot &source,
                      Snapshot &destination) {
  destination.registers.gpr27_configured = source.gpr27;
  destination.registers.gpio2_gdir_configured = source.gpio2_gdir;
  destination.registers.gpio2_psr_configured = source.gpio2_psr;
  destination.registers.pit_ldval_configured = source.pit_ldval;
  destination.registers.pit_tctrl_configured = source.pit_tctrl;
  destination.registers.dmamux_chcfg_configured = source.dmamux_chcfg;
  destination.registers.dma_erq_configured = source.dma_erq;
  destination.registers.tcd_citer_configured = source.tcd_citer;
  destination.registers.tcd_biter_configured = source.tcd_biter;
  destination.registers.tcd_csr_configured = source.tcd_csr;
  destination.registers.edma_priority_configured = source.edma_priority;
}

void recordAfter(const gpio_capture::HardwareSnapshot &source,
                 Snapshot &destination) {
  destination.registers.gpr27_after = source.gpr27;
  destination.registers.gpio2_gdir_after = source.gpio2_gdir;
  destination.registers.gpio2_psr_after = source.gpio2_psr;
  destination.registers.dma_err_final = source.dma_err;
  destination.dma_samples_captured =
      source.ring.progress.samples_captured;
}

void drainReady(gpio_capture::TeensyRawCapture &capture,
                Snapshot &snapshot) {
  for (std::size_t attempt = 0U;
       attempt < board::kGpioRawDmaRingDepth; ++attempt) {
    const gpio_capture::AcquireResult acquired = capture.acquireReady();
    if (acquired.status == gpio_capture::OperationStatus::kNoReadyBuffer) {
      return;
    }
    if (!acquired.ok() ||
        capture.release(acquired.handle) !=
            gpio_capture::OperationStatus::kOk) {
      addError(snapshot, Error::kCleanupFailed);
      return;
    }
  }
}

void analyze(const gpio_capture::RawWordDiagnosticLease &lease,
             Snapshot &snapshot) {
  if (!lease.valid()) {
    addError(snapshot, Error::kDiagnosticLeaseError);
    return;
  }

  snapshot.raw_word_and = std::numeric_limits<std::uint32_t>::max();
  snapshot.packed_value_and = std::numeric_limits<std::uint8_t>::max();
  std::uint8_t previous = 0U;
  for (std::uint32_t index = 0U; index < lease.sample_count; ++index) {
    const std::uint32_t raw = lease.words[index];
    const std::uint8_t packed = gpio_packer::packGpio2Word(raw);
    snapshot.raw_word_and &= raw;
    snapshot.raw_word_or |= raw;
    snapshot.packed_value_and =
        static_cast<std::uint8_t>(snapshot.packed_value_and & packed);
    snapshot.packed_value_or =
        static_cast<std::uint8_t>(snapshot.packed_value_or | packed);
    if (index == 0U) {
      snapshot.first_packed_value = packed;
    } else if (packed != previous) {
      ++snapshot.observed_transitions;
    }
    previous = packed;
  }
  snapshot.last_packed_value = previous;
  snapshot.samples_analyzed = lease.sample_count;
  snapshot.complete_samples_retained = lease.owner.sample_count;
  snapshot.packed_observation_exercised = true;
}

class TeensyPlatform final : public Platform {
 public:
  THINGDAQ_GPIO_DIAGNOSTIC_TARGET_CODE(
      ".flashmem.gpio_diagnostic.target")
  bool execute(const Plan &plan, Snapshot &snapshot) override {
    snapshot.mode = plan.mode;
    snapshot.fixture_identity = plan.fixture_identity;
    snapshot.stimulus_identity = plan.stimulus_identity;
    gpio_capture::TeensyRawCapture &capture =
        gpio_capture::teensyRawCapture();
    recordBefore(capture.snapshot(), snapshot);
    forceSafeInputs();

    // The installed fixture does not authorize output. Keep even future
    // unsupported plans fail-closed until their target path is reviewed on a
    // declared fixture.
    if (plan.mode != Mode::kNonDrivingCapture) {
      addError(snapshot, Error::kUnsupportedFixtureMode);
      recordConfigured(capture.snapshot(), snapshot);
      recordAfter(capture.snapshot(), snapshot);
      return true;
    }

    ARM_DEMCR |= ARM_DEMCR_TRCENA;
    ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
    const std::uint32_t dwt_probe = ARM_DWT_CYCCNT;
    __asm__ volatile("nop\n\tnop\n\tnop\n\tnop" : : : "memory");
    snapshot.dwt_counter_hz = F_CPU_ACTUAL;
    if (ARM_DWT_CYCCNT == dwt_probe ||
        F_CPU_ACTUAL != input_experiment::kCpuHz) {
      addError(snapshot, Error::kDwtUnavailable);
      forceSafeInputs();
      recordConfigured(capture.snapshot(), snapshot);
      recordAfter(capture.snapshot(), snapshot);
      return true;
    }

    const gpio_capture::StartStatus started = capture.start();
    if (started != gpio_capture::StartStatus::kOk) {
      if (started == gpio_capture::StartStatus::kResourceBusy) {
        addError(snapshot, Error::kResourceBusy);
      } else {
        addError(snapshot, Error::kCaptureFault);
      }
      forceSafeInputs();
      recordConfigured(capture.snapshot(), snapshot);
      recordAfter(capture.snapshot(), snapshot);
      return true;
    }

    snapshot.dma_capture_exercised = true;
    const std::uint32_t capture_begin = ARM_DWT_CYCCNT;
    gpio_capture::HardwareSnapshot active = capture.snapshot();
    while (active.ring.ready_depth == 0U && !active.faulted &&
           ARM_DWT_CYCCNT - capture_begin < kDiagnosticTimeoutCycles) {
      active = capture.snapshot();
    }
    snapshot.dwt_elapsed_cycles = ARM_DWT_CYCCNT - capture_begin;
    recordConfigured(active, snapshot);
    if (active.faulted) {
      addError(snapshot, Error::kCaptureFault);
    } else if (active.ring.ready_depth == 0U) {
      addError(snapshot, Error::kCaptureTimeout);
    }

    const gpio_capture::StopReport stopped = capture.stop();
    snapshot.stopped_partial_samples = stopped.active_samples_discarded;
    if (stopped.status != gpio_capture::OperationStatus::kOk) {
      addError(snapshot, Error::kCaptureFault);
    }

    gpio_capture::BoundedRawWordDiagnostic diagnostic{capture};
    const gpio_capture::RawWordDiagnosticAcquireResult acquired =
        diagnostic.acquire(plan.analysis_sample_limit);
    if (!acquired.ok()) {
      addError(snapshot, Error::kNoCompleteBuffer);
    } else {
      analyze(acquired.lease, snapshot);
      if (diagnostic.release(acquired.lease) !=
          gpio_capture::OperationStatus::kOk) {
        addError(snapshot, Error::kDiagnosticLeaseError);
      }
    }
    drainReady(capture, snapshot);
    const gpio_capture::HardwareSnapshot final = capture.snapshot();
    recordAfter(final, snapshot);
    if (!final.ring.quiescent) {
      addError(snapshot, Error::kCleanupFailed);
    }
    return true;
  }

  THINGDAQ_GPIO_DIAGNOSTIC_TARGET_CODE(
      ".flashmem.gpio_diagnostic.target")
  bool executeAuxiliary(const Plan &plan, Snapshot &snapshot) override {
    snapshot.mode = plan.mode;
    snapshot.fixture_identity = plan.fixture_identity;
    snapshot.stimulus_identity = plan.stimulus_identity;
    snapshot.auxiliary_capture = true;
    snapshot.aux_electrically_unstimulated = true;
    snapshot.aux_external_transition_checks_run = false;
    snapshot.configured_rate_hz = protocol_v1::kGpioSampleRateHz;
    gpio_join::TeensyDualBankCapture &capture =
        gpio_join::teensyDualBankCapture();
    const gpio_join::HardwareSnapshot before = capture.snapshot();
    snapshot.registers.gpr27_before = before.gpr27;
    snapshot.registers.gpr26_before = before.gpr26;
    snapshot.registers.gpio2_gdir_before = before.banks[0].gdir;
    snapshot.registers.gpio1_gdir_before = before.banks[1].gdir;
    snapshot.registers.gpio2_psr_before = before.banks[0].psr;
    snapshot.registers.gpio1_psr_before = before.banks[1].psr;
    if (plan.mode != Mode::kNonDrivingCapture) {
      addError(snapshot, Error::kUnsupportedFixtureMode);
      return true;
    }

    ARM_DEMCR |= ARM_DEMCR_TRCENA;
    ARM_DWT_CTRL |= ARM_DWT_CTRL_CYCCNTENA;
    const std::uint32_t dwt_probe = ARM_DWT_CYCCNT;
    __asm__ volatile("nop\n\tnop\n\tnop\n\tnop" : : : "memory");
    snapshot.dwt_counter_hz = F_CPU_ACTUAL;
    if (ARM_DWT_CYCCNT == dwt_probe ||
        F_CPU_ACTUAL != input_experiment::kCpuHz) {
      addError(snapshot, Error::kDwtUnavailable);
      return true;
    }

    const gpio_join::StartStatus started = capture.start(
        1U, protocol_v2::RateProfile::kAdc1mhzGpio4mhz);
    if (started != gpio_join::StartStatus::kOk) {
      addError(snapshot, started == gpio_join::StartStatus::kResourceBusy
                             ? Error::kResourceBusy
                             : Error::kCaptureFault);
      return true;
    }
    snapshot.dma_capture_exercised = true;
    const std::uint32_t capture_begin = ARM_DWT_CYCCNT;
    gpio_join::HardwareSnapshot active = capture.snapshot();
    while (active.ring.ready_depth == 0U && !active.ring.faulted &&
           ARM_DWT_CYCCNT - capture_begin < kDiagnosticTimeoutCycles) {
      active = capture.snapshot();
    }
    snapshot.dwt_elapsed_cycles = ARM_DWT_CYCCNT - capture_begin;
    snapshot.registers.gpr27_configured = active.gpr27;
    snapshot.registers.gpr26_configured = active.gpr26;
    snapshot.registers.gpio2_gdir_configured = active.banks[0].gdir;
    snapshot.registers.gpio1_gdir_configured = active.banks[1].gdir;
    snapshot.registers.gpio2_psr_configured = active.banks[0].psr;
    snapshot.registers.gpio1_psr_configured = active.banks[1].psr;
    snapshot.registers.pit_ldval_configured = active.pit_ldval;
    snapshot.registers.pit_tctrl_configured = active.pit_tctrl;
    snapshot.registers.dmamux_chcfg_configured =
        active.banks[0].dmamux_chcfg;
    snapshot.registers.aux_dmamux_chcfg_configured =
        active.banks[1].dmamux_chcfg;
    snapshot.registers.dma_erq_configured = active.dma_erq;
    snapshot.registers.aux_dma_erq_configured = active.dma_erq;
    snapshot.registers.tcd_citer_configured = active.banks[0].tcd_citer;
    snapshot.registers.aux_tcd_citer_configured = active.banks[1].tcd_citer;
    snapshot.registers.tcd_biter_configured = active.banks[0].tcd_biter;
    snapshot.registers.aux_tcd_biter_configured = active.banks[1].tcd_biter;
    snapshot.registers.tcd_csr_configured = active.banks[0].tcd_csr;
    snapshot.registers.aux_tcd_csr_configured = active.banks[1].tcd_csr;
    snapshot.registers.edma_priority_configured =
        active.banks[0].edma_priority;
    snapshot.registers.aux_edma_priority_configured =
        active.banks[1].edma_priority;
    if (active.ring.faulted) {
      addError(snapshot, Error::kCaptureFault);
    } else if (active.ring.ready_depth == 0U) {
      addError(snapshot, Error::kCaptureTimeout);
    }

    const gpio_join::StopReport stopped = capture.stop();
    snapshot.stopped_partial_samples =
        static_cast<std::uint32_t>(stopped.samples_discarded);
    snapshot.aux_stopped_partial_samples = snapshot.stopped_partial_samples;
    const gpio_join::AcquireResult acquired = capture.acquireReady();
    if (!acquired.ok()) {
      addError(snapshot, Error::kNoCompleteBuffer);
    } else {
      const std::uint32_t count =
          acquired.handle.sample_count < plan.analysis_sample_limit
              ? acquired.handle.sample_count
              : plan.analysis_sample_limit;
      snapshot.raw_word_and = std::numeric_limits<std::uint32_t>::max();
      snapshot.aux_raw_word_and =
          std::numeric_limits<std::uint32_t>::max();
      snapshot.packed_value_and = std::numeric_limits<std::uint8_t>::max();
      snapshot.aux_packed_value_and =
          std::numeric_limits<std::uint8_t>::max();
      std::uint8_t previous_primary = 0U;
      std::uint8_t previous_aux = 0U;
      for (std::uint32_t index = 0U; index < count; ++index) {
        const std::uint32_t primary_word = acquired.handle.primary_words[index];
        const std::uint32_t aux_word = acquired.handle.auxiliary_words[index];
        const std::uint8_t primary = gpio_packer::packGpio2Word(primary_word);
        const std::uint8_t aux = gpio_aux_packer::packGpio1Word(aux_word);
        snapshot.raw_word_and &= primary_word;
        snapshot.raw_word_or |= primary_word;
        snapshot.aux_raw_word_and &= aux_word;
        snapshot.aux_raw_word_or |= aux_word;
        snapshot.packed_value_and &= primary;
        snapshot.packed_value_or |= primary;
        snapshot.aux_packed_value_and &= aux;
        snapshot.aux_packed_value_or |= aux;
        if (index == 0U) {
          snapshot.first_packed_value = primary;
          snapshot.aux_first_packed_value = aux;
        } else {
          snapshot.observed_transitions += primary != previous_primary ? 1U : 0U;
          snapshot.aux_observed_transitions += aux != previous_aux ? 1U : 0U;
        }
        previous_primary = primary;
        previous_aux = aux;
      }
      snapshot.last_packed_value = previous_primary;
      snapshot.aux_last_packed_value = previous_aux;
      snapshot.samples_analyzed = count;
      snapshot.aux_samples_analyzed = count;
      snapshot.complete_samples_retained = acquired.handle.sample_count;
      snapshot.aux_complete_samples_retained = acquired.handle.sample_count;
      snapshot.packed_observation_exercised = true;
      if (capture.release(acquired.handle) !=
          gpio_join::OperationStatus::kOk) {
        addError(snapshot, Error::kDiagnosticLeaseError);
      }
    }
    (void)capture.serviceOwnership();
    const gpio_join::HardwareSnapshot final = capture.snapshot();
    snapshot.dma_samples_captured =
        final.ring.progress.bank_samples_completed[0];
    snapshot.aux_dma_samples_captured =
        final.ring.progress.bank_samples_completed[1];
    snapshot.cache_dma_discards = {
        final.ring.progress.cache_dma_discards / 2U,
        final.ring.progress.cache_dma_discards / 2U};
    snapshot.cache_cpu_invalidations = {
        final.ring.progress.cache_cpu_invalidations / 2U,
        final.ring.progress.cache_cpu_invalidations / 2U};
    snapshot.registers.gpr27_after = final.gpr27;
    snapshot.registers.gpr26_after = final.gpr26;
    snapshot.registers.gpio2_gdir_after = final.banks[0].gdir;
    snapshot.registers.gpio1_gdir_after = final.banks[1].gdir;
    snapshot.registers.gpio2_psr_after = final.banks[0].psr;
    snapshot.registers.gpio1_psr_after = final.banks[1].psr;
    snapshot.registers.dma_err_final = final.dma_err;
    snapshot.registers.aux_dma_err_final = final.dma_err;
    snapshot.final_input_safe =
        (final.banks[0].gdir & board::kGpio2PsrCaptureMask) == 0U &&
        (final.banks[1].gdir & board::kGpio1PsrCaptureMask) == 0U;
    if (!final.ring.quiescent || !snapshot.final_input_safe) {
      addError(snapshot, Error::kCleanupFailed);
    }
    return true;
  }
};

TeensyPlatform g_platform{};
Runner g_runner{kRegisteredTeensyFixture, g_platform};

}  // namespace

Runner &teensyRunner() { return g_runner; }

static_assert(F_CPU == input_experiment::kCpuHz,
              "GPIO capture diagnostic requires the pinned 600 MHz target");
static_assert(board::kGpioEdmaChannel == 2U);
static_assert(board::kGpioPitChannel == 0U);
static_assert(kDiagnosticTimeoutCycles == input_experiment::scaleDwt(6000000U));

}  // namespace thingdaq::gpio_diagnostic

#undef THINGDAQ_GPIO_DIAGNOSTIC_TARGET_CODE

#endif
