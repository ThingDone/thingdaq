#pragma once
#include <cstdint>
extern "C" {
struct usb_string_descriptor_struct {
  std::uint8_t bLength;
  std::uint8_t bDescriptorType;
  std::uint16_t wString[10];
};
extern usb_string_descriptor_struct usb_string_serial_number;
}
