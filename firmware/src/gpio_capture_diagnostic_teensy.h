#pragma once

#include "gpio_capture_diagnostic.h"

namespace teensy_daq::gpio_diagnostic {

// The registered Port 15 documentation identifies the board and upload path
// but contains no machine-readable pin-safety, loopback, or stimulus record.
// This declaration therefore selects the non-driving mode unconditionally.
inline constexpr FixtureDeclaration kRegisteredTeensyFixture{
    MetadataKind::kDocumentationOnly,
    DriveSafety::kUnspecified,
    StimulusKind::kNone,
    0U,
    0U,
    0U,
    0U,
};

Runner &teensyRunner();

static_assert(kRegisteredTeensyFixture.metadata_kind ==
              MetadataKind::kDocumentationOnly);
static_assert(kRegisteredTeensyFixture.drive_safety ==
              DriveSafety::kUnspecified);

}  // namespace teensy_daq::gpio_diagnostic
