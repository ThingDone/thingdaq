#include <cassert>
#include <array>
#include <core_pins.h>
#include <imxrt.h>
#include <usb_names.h>
#include <usb_serial.h>

#include "teensy_usb.h"

volatile std::uint8_t usb_cdc_line_rtsdtr = USB_SERIAL_DTR;
usb_string_descriptor_struct usb_string_serial_number{};
int free_bytes = 2048;
int write_result = 24;
unsigned int write_calls = 0U;

int usb_serial_available() { return 0; }
int usb_serial_read(void *, std::uint32_t) { return 0; }

void expectProtected() {
  assert(!NVIC_IS_ENABLED(IRQ_USB1));
  assert(fake_imxrt::interrupts_enabled);
  assert(NVIC_IS_ENABLED(IRQ_DMA_CH0));
  assert(NVIC_IS_ENABLED(IRQ_DMA_CH1));
  assert(NVIC_IS_ENABLED(IRQ_DMA_CH2));
  assert(NVIC_IS_ENABLED(IRQ_DMA_CH3));
  // A timer request arriving in the call must remain pending for later service.
  fake_imxrt::interrupt_pending[IRQ_USB1] = true;
}

int usb_serial_write_buffer_free() {
  expectProtected();
  return free_bytes;
}
int usb_serial_write(const void *, std::uint32_t) {
  expectProtected();
  ++write_calls;
  return write_result;
}

int main() {
  thingdaq::usb::TeensyCdcByteStream stream;
  std::array<std::uint8_t, 1025U> bytes{};
  for (auto irq : {IRQ_DMA_CH0, IRQ_DMA_CH1, IRQ_DMA_CH2, IRQ_DMA_CH3}) {
    NVIC_ENABLE_IRQ(irq);
  }
  for (bool enabled : {true, false}) {
    fake_imxrt::interrupt_enabled[IRQ_USB1] = enabled;
    free_bytes = 2048;
    assert(stream.availableForWrite() == 2048);
    assert(NVIC_IS_ENABLED(IRQ_USB1) == enabled);
    for (int accepted : {24, 7, 0, -1}) {
      write_result = accepted;
      assert(stream.write(bytes.data(), 24U) == accepted);
      assert(NVIC_IS_ENABLED(IRQ_USB1) == enabled);
      assert(fake_imxrt::interrupt_pending[IRQ_USB1]);
    }
    const auto previous_calls = write_calls;
    // Capacity disappeared since the caller's earlier availableForWrite().
    free_bytes = 0;
    assert(stream.write(bytes.data(), 24U) == thingdaq::usb::kWriteWouldBlock);
    assert(write_calls == previous_calls);
    assert(NVIC_IS_ENABLED(IRQ_USB1) == enabled);
    assert(stream.write(bytes.data(), bytes.size()) == -1);
    assert(stream.write(nullptr, 24U) == -1);
    assert(stream.write(bytes.data(), 0U) == -1);
    usb_cdc_line_rtsdtr = 0;
    assert(stream.write(bytes.data(), 24U) == 0);
    assert(stream.availableForWrite() == 0);
    assert(write_calls == previous_calls);
    assert(NVIC_IS_ENABLED(IRQ_USB1) == enabled);
    usb_cdc_line_rtsdtr = USB_SERIAL_DTR;
  }
}
