#pragma once

#include "digital_output_engine.h"

namespace thingdaq::digital_output {

struct HardwareSnapshot {
  Snapshot engine{};
  std::uint32_t gpr26 = 0U;
  std::uint32_t gpio1_dr = 0U;
  std::uint32_t gpio1_gdir = 0U;
  std::uint32_t gpio6_gdir = 0U;
  std::uint32_t dmamux_chcfg = 0U;
  std::uint32_t dma_erq = 0U;
  std::uint32_t dma_err = 0U;
  std::uint16_t xbar_selection = 0U;
  std::uint16_t xbar_control = 0U;
  std::uint16_t tcd_citer = 0U;
  std::uint16_t tcd_biter = 0U;
  std::uint16_t tcd_csr = 0U;
  std::uint8_t edma_priority = 0U;
  std::uint32_t resource_conflicts = 0U;
  std::uint32_t target_start_errors = 0U;
  std::uint32_t target_stop_errors = 0U;
  std::uint32_t stale_dma_completions = 0U;
  bool pins_claimed = false;
  bool hardware_prepared = false;
  bool hardware_running = false;
};

// Target facade that keeps the portable program/ring engine authoritative and
// confines every pin, XBAR, DMAMUX, eDMA, cache, and IRQ operation to one
// Teensy-only translation unit.
class TeensyOutput final : public Participant {
 public:
  ~TeensyOutput() override;
  ProgramStatus begin(std::uint32_t generation, std::uint32_t repeat_count,
                      std::uint32_t idle_state_mask);
  ProgramStatus append(std::uint32_t generation, const Segment &segment);
  ProgramStatus commit(std::uint32_t generation,
                       std::size_t expected_segment_count,
                       std::uint32_t expected_checksum);
  OperationStatus arm(std::uint32_t generation);
  OperationStatus clear();

  ProgramStatus controlBegin(std::uint32_t generation,
                             std::uint32_t repeat_count,
                             std::uint32_t idle_state_mask) override {
    return begin(generation, repeat_count, idle_state_mask);
  }
  ProgramStatus controlAppend(std::uint32_t generation,
                              const Segment &segment) override {
    return append(generation, segment);
  }
  ProgramStatus controlCommit(std::uint32_t generation,
                              std::size_t expected_segment_count,
                              std::uint32_t expected_checksum) override {
    return commit(generation, expected_segment_count, expected_checksum);
  }
  OperationStatus controlArm(std::uint32_t generation) override {
    return arm(generation);
  }
  OperationStatus controlClear() override { return clear(); }

  bool participatesInNextStart() const override;
  StartStatus inspectStart(std::uint32_t run_id) const override;
  StartStatus prepareStart(std::uint32_t run_id,
                           std::uint64_t epoch_ticks) override;
  void commitCommonStart() override;
  void rollbackPreparedStart() override;
  StopReport stopAfterTriggers() override;
  ServiceReport service(std::size_t block_limit) override;
  Snapshot snapshot() const override;
  bool faulted() const override;

  HardwareSnapshot hardwareSnapshot() const;

 private:
  explicit constexpr TeensyOutput(Engine &engine) : engine_(engine) {}
  Engine &engine_;

  friend TeensyOutput &teensyOutput(
      ProgramStorage &, DmaBlockStorage &, DmaDescriptorStorage &);
};

// This factory is side-effect free with respect to hardware. It binds the
// linker-accounted sketch allocations during static construction; D16-D23
// remain GPIO6 inputs until an explicit successful arm().
TeensyOutput &teensyOutput(ProgramStorage &program_storage,
                           DmaBlockStorage &dma_storage,
                           DmaDescriptorStorage &descriptor_storage);

}  // namespace thingdaq::digital_output
