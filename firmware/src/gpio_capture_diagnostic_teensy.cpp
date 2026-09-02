#include "gpio_capture_diagnostic_teensy.h"

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <cstddef>
#include <cstdint>
#include <limits>

#include <core_pins.h>
#include <imxrt.h>

#include "firmware_identity.h"
#include "gpio_batch_packer.h"
#include "gpio_raw_capture_teensy.h"

#define THINGDAQ_GPIO_DIAGNOSTIC_TARGET_CODE(section_name) \
  __attribute__((section(section_name), noinline, noipa, used))

namespace thingdaq::gpio_diagnostic {
namespace {

constexpr std::uint32_t kDiagnosticTimeoutCycles =
    identity::dwtCyclesForMicroseconds(10000U);

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
        F_CPU_ACTUAL != identity::kExpectedDwtHz) {
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
};

TeensyPlatform g_platform{};
Runner g_runner{kRegisteredTeensyFixture, g_platform};

}  // namespace

Runner &teensyRunner() { return g_runner; }

static_assert(F_CPU == identity::kExpectedCpuHz,
              "GPIO capture diagnostic requires the selected CPU profile");
static_assert(board::kGpioEdmaChannel == 2U);
static_assert(board::kGpioPitChannel == 0U);
static_assert(kDiagnosticTimeoutCycles ==
              identity::kExpectedDwtHz / 100U);

}  // namespace thingdaq::gpio_diagnostic

#undef THINGDAQ_GPIO_DIAGNOSTIC_TARGET_CODE

#endif
