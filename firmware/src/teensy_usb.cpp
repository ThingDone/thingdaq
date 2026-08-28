#include "teensy_usb.h"

#include <limits>

namespace teensy_daq::usb {

bool parseDecimalHardwareSerial(const std::uint16_t *code_units,
                                std::size_t code_unit_count,
                                std::uint32_t &hardware_serial) {
  if (code_units == nullptr || code_unit_count == 0U ||
      code_unit_count > 10U) {
    return false;
  }

  std::uint32_t value = 0U;
  constexpr std::uint32_t maximum =
      std::numeric_limits<std::uint32_t>::max();
  for (std::size_t index = 0U; index < code_unit_count; ++index) {
    const std::uint16_t code_unit = code_units[index];
    if (code_unit < static_cast<std::uint16_t>('0') ||
        code_unit > static_cast<std::uint16_t>('9')) {
      return false;
    }
    const std::uint32_t digit =
        static_cast<std::uint32_t>(code_unit -
                                   static_cast<std::uint16_t>('0'));
    if (value > (maximum - digit) / 10U) {
      return false;
    }
    value = value * 10U + digit;
  }
  hardware_serial = value;
  return true;
}

}  // namespace teensy_daq::usb

#if defined(ARDUINO_TEENSY40) && defined(__IMXRT1062__)

#include <Arduino.h>
#include <usb_desc.h>
#include <usb_names.h>
#include <usb_serial.h>

static_assert(VENDOR_ID == teensy_daq::usb::kTeensyUsbSerialVendorId,
              "pinned Teensy USB Serial VID changed");
static_assert(PRODUCT_ID == teensy_daq::usb::kTeensyUsbSerialProductId,
              "pinned Teensy USB Serial PID changed");
static_assert(teensy_daq::identity::kUsbProductNameUtf16.size() == 10U);

// usb_desc.c publishes this symbol as a weak alias. Supplying the strong
// project definition changes only descriptor index 2. The core's weak serial
// symbol and usb_init_serialnumber() remain untouched and chip-derived.
extern "C" {
struct usb_string_descriptor_struct usb_string_product_name = {
    2U + teensy_daq::identity::kUsbProductNameUtf16.size() * 2U,
    teensy_daq::usb::kUsbStringDescriptorType,
    {
        teensy_daq::identity::kUsbProductNameUtf16[0],
        teensy_daq::identity::kUsbProductNameUtf16[1],
        teensy_daq::identity::kUsbProductNameUtf16[2],
        teensy_daq::identity::kUsbProductNameUtf16[3],
        teensy_daq::identity::kUsbProductNameUtf16[4],
        teensy_daq::identity::kUsbProductNameUtf16[5],
        teensy_daq::identity::kUsbProductNameUtf16[6],
        teensy_daq::identity::kUsbProductNameUtf16[7],
        teensy_daq::identity::kUsbProductNameUtf16[8],
        teensy_daq::identity::kUsbProductNameUtf16[9],
    },
};
}

namespace teensy_daq::usb {

IoCount TeensyCdcByteStream::available() {
  return static_cast<IoCount>(usb_serial_available());
}

IoCount TeensyCdcByteStream::read(std::uint8_t *destination,
                                  std::size_t capacity) {
  if (destination == nullptr || capacity == 0U ||
      capacity > std::numeric_limits<std::uint32_t>::max()) {
    return -1;
  }
  return static_cast<IoCount>(
      usb_serial_read(destination, static_cast<std::uint32_t>(capacity)));
}

IoCount TeensyCdcByteStream::availableForWrite() {
  return static_cast<IoCount>(usb_serial_write_buffer_free());
}

IoCount TeensyCdcByteStream::write(const std::uint8_t *source,
                                   std::size_t size) {
  if (source == nullptr || size == 0U ||
      size > std::numeric_limits<std::uint32_t>::max()) {
    return -1;
  }
  return static_cast<IoCount>(
      usb_serial_write(source, static_cast<std::uint32_t>(size)));
}

std::uint32_t hardwareSerialNumber() {
  const std::uint8_t descriptor_bytes = usb_string_serial_number.bLength;
  if (descriptor_bytes < 2U || (descriptor_bytes - 2U) % 2U != 0U) {
    return 0U;
  }
  const std::size_t code_units = (descriptor_bytes - 2U) / 2U;
  std::uint32_t hardware_serial = 0U;
  return parseDecimalHardwareSerial(usb_string_serial_number.wString,
                                    code_units, hardware_serial)
             ? hardware_serial
             : 0U;
}

}  // namespace teensy_daq::usb

#endif
