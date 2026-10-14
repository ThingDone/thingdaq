#pragma once
// Standalone, destructive ADC timing characterization; never a production image.
// Build instructions and measurement limitations are in README.md.
#include <Arduino.h>
#include <DMAChannel.h>
#if F_CPU != 450000000 && F_CPU != 528000000
#error "Probe supports only the 450 MHz control and 528 MHz candidate"
#endif
#define THINGDAQ_EXPERIMENT_CPU_HZ F_CPU
#include <adc_initializer.cpp>
#include <variable_rate_scheduler.cpp>
#include <variable_rate_scheduler_teensy.cpp>
#include <adc_trigger.cpp>
#include <adc_initializer_teensy.cpp>
#include <adc_trigger_teensy.cpp>

namespace probe {
namespace tr = thingdaq::adc_trigger;
void software(unsigned direct, unsigned converter) {
  auto &a = converter == 0 ? IMXRT_ADC1 : IMXRT_ADC2;
  a.CFG = ADC_CFG_OVWREN | ADC_CFG_ADHSC | ADC_CFG_MODE(2) |
          (direct ? ADC_CFG_ADIV(2) : ADC_CFG_ADIV(1) | ADC_CFG_ADICLK(1));
  a.GC = 0;
  for (unsigned iteration = 0; iteration < 4; ++iteration) {
    uint32_t elapsed, result;
    {
    const auto guard = thingdaq::interrupts::Guard{};
    (void)a.R0;
    const uint32_t start = ARM_DWT_CYCCNT;
    a.HC0 = ADC_HC_ADCH(converter == 0 ? 7 : 8);
    while (!(a.HS & ADC_HS_COCO0) && ARM_DWT_CYCCNT-start < (F_CPU / 10000)) {}
    elapsed = ARM_DWT_CYCCNT-start;
    result = a.R0;
    }
    Serial.printf("PROBE {\"kind\":\"software\",\"direct\":%u,\"adc\":%u,\"iteration\":%u,\"cycles\":%lu,\"code\":%lu,\"cfg\":%lu}\n",direct,converter,iteration,elapsed,result,a.CFG);
  }
  a.HC0 = ADC_HC_ADCH(31);
}
void periodic(unsigned direct, unsigned ticks, unsigned mask, unsigned b2b) {
  tr::TeensyPlatform platform;
  auto configured = platform.configureStopped();
  if (configured.error_flags) {
    Serial.printf("PROBE {\"configure_error\":%lu}\n",configured.error_flags);return;
  }
  for (auto a : {&IMXRT_ADC1,&IMXRT_ADC2}) {
    a->CFG = ADC_CFG_OVWREN | ADC_CFG_ADHSC | ADC_CFG_MODE(2) | ADC_CFG_ADTRG |
          (direct ? ADC_CFG_ADIV(2) : ADC_CFG_ADIV(1) | ADC_CFG_ADICLK(1));
  }
  for (auto i : {0U,4U}) if (b2b) IMXRT_ADC_ETC.TRIG[i].CHAIN_1_0 |= ADC_ETC_TRIG_CHAIN_B2B0;
  uint32_t done[2]={}, errors=0, bits=0, first[2]={}, last[2]={};
  uint32_t min_delta[2]={0xffffffff,0xffffffff},max_delta[2]={};
  uint32_t elapsed;
  {
    const auto guard = thingdaq::interrupts::Guard{};
    IMXRT_PIT_CHANNELS[0].LDVAL = ticks-1;
    IMXRT_PIT_CHANNELS[1].LDVAL = 0;
    IMXRT_PIT_CHANNELS[0].TFLG = 1;
    IMXRT_PIT_CHANNELS[1].TFLG = 1;
    ADC_ETC_DONE0_1_IRQ = tr::kDone0Mask | tr::kDone1Mask;
    ADC_ETC_DONE2_ERR_IRQ = tr::kTriggerErrorMask;
    ADC_ETC_CTRL = ADC_ETC_CTRL_TRIG_ENABLE(mask);
    IMXRT_PIT_CHANNELS[1].TCTRL = PIT_TCTRL_CHN | PIT_TCTRL_TEN;
    const uint32_t start=ARM_DWT_CYCCNT;
    IMXRT_PIT_CHANNELS[0].TCTRL = PIT_TCTRL_TEN;
    do {
      uint32_t pending=ADC_ETC_DONE0_1_IRQ & (tr::kDone0Mask|tr::kDone1Mask);
      uint32_t error=ADC_ETC_DONE2_ERR_IRQ & tr::kTriggerErrorMask;
      uint32_t now=ARM_DWT_CYCCNT-start;
      if(pending) ADC_ETC_DONE0_1_IRQ=pending;
      if(error) {ADC_ETC_DONE2_ERR_IRQ=error; ++errors;bits|=error;}
      for(unsigned i=0;i<2;++i) if(pending & (i==0?tr::kDone0Mask:tr::kDone1Mask)) {
        if(!done[i])first[i]=now;
        else {uint32_t delta=now-last[i];if(delta<min_delta[i])min_delta[i]=delta;if(delta>max_delta[i])max_delta[i]=delta;}
        last[i]=now;++done[i];
      }
      elapsed=now;
    }while(elapsed<(F_CPU / 1000));
    IMXRT_PIT_CHANNELS[0].TCTRL=0;
    IMXRT_PIT_CHANNELS[1].TCTRL=PIT_TCTRL_CHN;
    ADC_ETC_CTRL=0;
  }
  bool stopped=platform.stop();
  Serial.printf("PROBE {\"kind\":\"periodic\",\"direct\":%u,\"ticks\":%u,\"mask\":%u,\"b2b\":%u,\"cycles\":%lu,\"done0\":%lu,\"done1\":%lu,\"errors\":%lu,\"error_bits\":%lu,\"first0\":%lu,\"first1\":%lu,\"min0\":%lu,\"max0\":%lu,\"min1\":%lu,\"max1\":%lu,\"stopped\":%u}\n",direct,ticks,mask,b2b,elapsed,done[0],done[1],errors,bits,first[0],first[1],min_delta[0],max_delta[0],min_delta[1],max_delta[1],stopped);
}
DMAMEM uint32_t sample_buffer[4096] __attribute__((aligned(32)));
DMAMEM uint32_t channel_word[8] __attribute__((aligned(32)));
void dmaSoftware(unsigned direct, unsigned ticks, unsigned converter) {
  namespace route=thingdaq::gpio_dma_route;
  route::enableClockGates();
  route::configureStoppedPit(ticks-1);
  ADC_ETC_CTRL=0;
  auto &a=converter==0?IMXRT_ADC1:IMXRT_ADC2;
  a.CFG=ADC_CFG_OVWREN|ADC_CFG_ADHSC|ADC_CFG_MODE(2)|
        (direct?ADC_CFG_ADIV(2):ADC_CFG_ADIV(1)|ADC_CFG_ADICLK(1));
  a.HC0=ADC_HC_ADCH(31);a.GC=0;(void)a.R0;
  channel_word[0]=converter==0?7:8;
  arm_dcache_flush(channel_word,sizeof(channel_word));
  arm_dcache_delete(sample_buffer,sizeof(sample_buffer));
  DMAChannel trigger, result;
  trigger.source(channel_word[0]);trigger.destination(a.HC0);
  trigger.transferCount(2048);trigger.disableOnCompletion();
  trigger.triggerAtHardwareEvent(DMAMUX_SOURCE_XBAR1_0);
  result.source(a.R0);result.destinationBuffer(sample_buffer,sizeof(sample_buffer));
  result.disableOnCompletion();
  result.triggerAtHardwareEvent(converter==0?DMAMUX_SOURCE_ADC1:DMAMUX_SOURCE_ADC2);
  XBARA1_SEL0=(XBARA1_SEL0&0xff00)|XBARA1_IN_PIT_TRIGGER0;
  XBARA1_CTRL0=XBARA_CTRL_STS0|XBARA_CTRL_EDGE0(1)|XBARA_CTRL_DEN0;
  a.GC=ADC_GC_DMAEN;
  uint32_t elapsed;
  {
    const auto guard=thingdaq::interrupts::Guard{};
    result.enable();trigger.enable();
    uint32_t start=ARM_DWT_CYCCNT;
    IMXRT_PIT_CHANNELS[0].TCTRL=PIT_TCTRL_TEN;
    while(ARM_DWT_CYCCNT-start<(F_CPU / 1000)){}
    IMXRT_PIT_CHANNELS[0].TCTRL=0;
    elapsed=ARM_DWT_CYCCNT-start;
    start=ARM_DWT_CYCCNT;while(ARM_DWT_CYCCNT-start<(F_CPU / 100000)){}
    trigger.disable();result.disable();
  }
  const uint32_t triggers=2048-trigger.TCD->CITER_ELINKNO;
  const uint32_t samples=4096-result.TCD->CITER_ELINKNO;
  a.GC=0;a.HC0=ADC_HC_ADCH(31);XBARA1_CTRL0=XBARA_CTRL_STS0;
  arm_dcache_delete(sample_buffer,sizeof(sample_buffer));
  unsigned invalid=0;for(unsigned i=0;i<samples && i<4096;++i)if(sample_buffer[i]>4095)++invalid;
  Serial.printf("PROBE {\"kind\":\"dma-software\",\"direct\":%u,\"ticks\":%u,\"adc\":%u,\"cycles\":%lu,\"triggers\":%lu,\"samples\":%lu,\"dma_errors\":%lu,\"invalid_codes\":%u}\n",direct,ticks,converter,elapsed,triggers,samples,DMA_ERR,invalid);
}
void continuous(unsigned direct, unsigned converter, unsigned sample) {
  auto &a=converter==0?IMXRT_ADC1:IMXRT_ADC2;
  ADC_ETC_CTRL=0;
  a.HC0=ADC_HC_ADCH(31);a.GC=0;(void)a.R0;
  a.CFG=ADC_CFG_OVWREN|ADC_CFG_ADHSC|ADC_CFG_MODE(2)|ADC_CFG_ADSTS(sample)|
        (direct?ADC_CFG_ADIV(2):ADC_CFG_ADIV(1)|ADC_CFG_ADICLK(1));
  arm_dcache_delete(sample_buffer,sizeof(sample_buffer));
  DMAChannel result;
  result.source(a.R0);result.destinationBuffer(sample_buffer,sizeof(sample_buffer));
  result.disableOnCompletion();
  result.triggerAtHardwareEvent(converter==0?DMAMUX_SOURCE_ADC1:DMAMUX_SOURCE_ADC2);
  a.GC=ADC_GC_DMAEN|ADC_GC_ADCO;
  uint32_t elapsed;
  {
    const auto guard=thingdaq::interrupts::Guard{};
    result.enable();
    uint32_t start=ARM_DWT_CYCCNT;
    a.HC0=ADC_HC_ADCH(converter==0?7:8);
    while(ARM_DWT_CYCCNT-start<F_CPU/1000){}
    a.HC0=ADC_HC_ADCH(31);
    elapsed=ARM_DWT_CYCCNT-start;
    result.disable();
  }
  const uint32_t samples=4096-result.TCD->CITER_ELINKNO;
  a.GC=0;
  arm_dcache_delete(sample_buffer,sizeof(sample_buffer));
  unsigned invalid=0;for(unsigned i=0;i<samples && i<4096;++i)if(sample_buffer[i]>4095)++invalid;
  Serial.printf("PROBE {\"kind\":\"continuous\",\"direct\":%u,\"adc\":%u,\"adsts\":%u,\"cycles\":%lu,\"samples\":%lu,\"dma_errors\":%lu,\"invalid_codes\":%u}\n",direct,converter,sample,elapsed,samples,DMA_ERR,invalid);
}
DMAMEM uint32_t soak_buffer[2][16384] __attribute__((aligned(32)));
void runSoak() {
  const auto &initialized=thingdaq::adc::teensyInitializer().initialize();
  Serial.printf("PROBE {\"kind\":\"identity\",\"cpu\":%lu,\"ipg\":%lu,\"ready\":%u,\"errors\":%lu}\n",F_CPU_ACTUAL,F_BUS_ACTUAL,initialized.ready(),initialized.initialization_error_flags);
  if(!initialized.ready())return;
  ADC_ETC_CTRL=0;
  DMAChannel channels[2];
  for(unsigned i=0;i<2;++i) {
    auto &a=i==0?IMXRT_ADC1:IMXRT_ADC2;
    a.HC0=ADC_HC_ADCH(31);a.GC=0;(void)a.R0;
    a.CFG=ADC_CFG_OVWREN|ADC_CFG_ADHSC|ADC_CFG_MODE(2)|ADC_CFG_ADIV(1)|ADC_CFG_ADICLK(1);
    arm_dcache_delete(soak_buffer[i],sizeof(soak_buffer[i]));
    channels[i].source(a.R0);
    channels[i].destinationBuffer(soak_buffer[i],sizeof(soak_buffer[i]));
    channels[i].triggerAtHardwareEvent(i==0?DMAMUX_SOURCE_ADC1:DMAMUX_SOURCE_ADC2);
    a.GC=ADC_GC_DMAEN|ADC_GC_ADCO;
    channels[i].enable();
  }
  uint64_t samples[2]={},elapsed=0;
  uint32_t previous[2]={16384,16384},maximum_poll=0,errors=0;
  uint32_t previous_clock=ARM_DWT_CYCCNT;
  IMXRT_ADC1.HC0=ADC_HC_ADCH(7);
  IMXRT_ADC2.HC0=ADC_HC_ADCH(8);
  while(elapsed<uint64_t(F_CPU)*60) {
    for(unsigned i=0;i<2;++i) {
      uint32_t current=channels[i].TCD->CITER_ELINKNO;
      samples[i]+=(previous[i]+16384-current)%16384;
      previous[i]=current;
    }
    uint32_t current_clock=ARM_DWT_CYCCNT;
    uint32_t delta=current_clock-previous_clock;
    elapsed+=delta;if(delta>maximum_poll)maximum_poll=delta;
    previous_clock=current_clock;errors|=DMA_ERR;
  }
  // Counts are the last sampled CITER values; register writes after this
  // boundary may permit a few additional transfers, which are not counted.
  IMXRT_ADC1.HC0=ADC_HC_ADCH(31);IMXRT_ADC2.HC0=ADC_HC_ADCH(31);
  for(auto &channel:channels)channel.disable();
  IMXRT_ADC1.GC=0;IMXRT_ADC2.GC=0;
  arm_dcache_delete(soak_buffer,sizeof(soak_buffer));
  uint32_t invalid=0;
  for(auto &buffer:soak_buffer)for(auto value:buffer)if(value>4095)++invalid;
  Serial.printf("PROBE {\"kind\":\"dual-continuous-soak\",\"cycles\":%llu,\"samples0\":%llu,\"samples1\":%llu,\"max_poll_cycles\":%lu,\"dma_errors\":%lu,\"invalid_final_buffer_codes\":%lu,\"seconds_requested\":60}\n",elapsed,samples[0],samples[1],maximum_poll,errors,invalid);
  Serial.println("PROBE_DONE");
}
void runContinuous() {
  const auto &a=thingdaq::adc::teensyInitializer().initialize();
  Serial.printf("PROBE {\"kind\":\"identity\",\"cpu\":%lu,\"ipg\":%lu,\"ready\":%u,\"errors\":%lu}\n",F_CPU_ACTUAL,F_BUS_ACTUAL,a.ready(),a.initialization_error_flags);
  if(!a.ready())return;
  for(unsigned direct:{0U,1U})for(unsigned adc:{0U,1U})for(unsigned sample:{0U,1U,2U,3U})continuous(direct,adc,sample);
  Serial.println("PROBE_DONE");
}
void runDma() {
  const auto &a=thingdaq::adc::teensyInitializer().initialize();
  Serial.printf("PROBE {\"kind\":\"identity\",\"cpu\":%lu,\"ipg\":%lu,\"ready\":%u,\"errors\":%lu}\n",F_CPU_ACTUAL,F_BUS_ACTUAL,a.ready(),a.initialization_error_flags);
  if(!a.ready())return;
  for(unsigned direct:{0U,1U})for(unsigned adc:{0U,1U})for(unsigned ticks:{48U,26U,25U,24U})dmaSoftware(direct,ticks,adc);
  Serial.println("PROBE_DONE");
}
void run() {
  const auto &a=thingdaq::adc::teensyInitializer().initialize();
  Serial.printf("PROBE {\"kind\":\"identity\",\"cpu\":%lu,\"ipg\":%lu,\"ready\":%u,\"errors\":%lu,\"serial\":%lu}\n",F_CPU_ACTUAL,F_BUS_ACTUAL,a.ready(),a.initialization_error_flags,HW_OCOTP_MAC0 & 0xffffff);
  if(!a.ready())return;
  for(unsigned direct : {0U,1U}) {
    software(direct,0);software(direct,1);
    for(unsigned b2b : {0U,1U}) for(unsigned mask : {1U,16U,17U}) for(unsigned ticks : {48U,32U,28U,26U,25U,24U})periodic(direct,ticks,mask,b2b);
  }
  Serial.println("PROBE_DONE");
}
}
void setup() { Serial.begin(115200); }
void loop() { if(Serial.available()){auto command=Serial.read();if(command=='r')probe::run();else if(command=='d')probe::runDma();else if(command=='c')probe::runContinuous();else if(command=='s')probe::runSoak();} }
