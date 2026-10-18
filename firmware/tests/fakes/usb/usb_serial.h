#pragma once
#include <cstdint>
#define USB_SERIAL_DTR 1U
extern volatile std::uint8_t usb_cdc_line_rtsdtr;
int usb_serial_available();
int usb_serial_read(void *, std::uint32_t);
int usb_serial_write_buffer_free();
int usb_serial_write(const void *, std::uint32_t);
