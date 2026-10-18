// Reuse the existing register fixture and real target adapters.
#define main ordinary_adc_register_tests
#include "adc_register_adapter_test.cpp"
#undef main

int main() {
  resetFakeRegisters();
  trigger::TeensyPlatform platform{};
  expect(platform.configureStopped().error_flags == 0U, "probe configures stopped");
  ADC_ETC_DMA_CTRL = ADC_ETC_DMA_CTRL_TRIQ_REQ(4U) |
                     ADC_ETC_DMA_CTRL_TRIQ_ENABLE(4U);
  expect(platform.armFromStopped(false), "ETC request source arms");
  expect((ADC_ETC_CTRL & ADC_ETC_CTRL_DMA_MODE_SEL) != 0U,
         "ETC request uses acknowledgement-cleared mode");
  expect(platform.stop(), "ETC request source stops");
  expect((ADC_ETC_CTRL & ADC_ETC_CTRL_DMA_MODE_SEL) != 0U &&
             (ADC_ETC_DMA_CTRL & 0xFFU) == 0x10U,
         "trigger stop preserves handshake through final conversion");
  // ADC DMA teardown owns disabling its request source and clearing mode.
  ADC_ETC_DMA_CTRL = ADC_ETC_DMA_CTRL_TRIQ_REQ(4U);
  ADC_ETC_CTRL &= ~ADC_ETC_CTRL_DMA_MODE_SEL;
  expect(platform.armFromStopped(false), "original ADC request route can restart");
  expect((ADC_ETC_CTRL & ADC_ETC_CTRL_DMA_MODE_SEL) == 0U,
         "original route retains original mode");
  expect(platform.stop(), "original route stops");
  return failures == 0 ? 0 : 1;
}
