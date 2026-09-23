#pragma once

#if defined(THINGDAQ_EXPERIMENT_USB_THROUGHPUT)
#include "packet_buffer_pipeline.h"
#include "teensy_usb.h"

namespace thingdaq::usb_throughput {
bool active();
// Research-only command interface; borrows idle packet pages, never drives pins.
void service(usb::TeensyCdcByteStream &stream,
             packet::PacketBufferPrimaryStorage &storage);
}
#endif
