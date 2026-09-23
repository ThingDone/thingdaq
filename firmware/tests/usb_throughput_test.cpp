#include <algorithm>
#include <cassert>
#include <fstream>
#include <string>
#include <vector>
#include "../src/usb_throughput_experiment.cpp"

volatile uint8_t usb_high_speed = 1;
std::uint32_t fake_time = 0;
std::uint32_t micros() { return fake_time; }
std::string input;
std::vector<std::uint8_t> output;
std::size_t max_write = 8192;
bool connected = true;
namespace thingdaq::usb {
bool TeensyCdcByteStream::sessionOpen() const { return connected; }
IoCount TeensyCdcByteStream::available() { return static_cast<IoCount>(input.size()); }
IoCount TeensyCdcByteStream::read(std::uint8_t *p, std::size_t) {
  if (input.empty()) return 0;
  *p = static_cast<std::uint8_t>(input.front()); input.erase(0, 1); return 1;
}
IoCount TeensyCdcByteStream::availableForWrite() { return 8192; }
IoCount TeensyCdcByteStream::write(const std::uint8_t *p, std::size_t size) {
  const auto n = std::min(size, max_write);
  output.insert(output.end(), p, p + n); return static_cast<IoCount>(n);
}
std::uint32_t hardwareSerialNumber() { return 20428100; }
}

int main(int argc, char **argv) {
  assert(argc == 2);
  fake_imxrt::f_cpu_actual = 450000000U;
  using namespace thingdaq;
  std::uint32_t values[3]{};
  assert(usb_throughput::parseRun("RUN 1 100 0", values));
  for (const auto *invalid : {"RUN -1 100 0", "RUN 1 100 0 x", "RUN 1 100", "RUN 4294967296 100 0", "RUB 1 100 0"})
    assert(!usb_throughput::parseRun(invalid, values));
  static packet::PacketBufferPrimaryStorage storage;
  usb::TeensyCdcByteStream stream;
  input = "INFO\n";
  usb_throughput::service(stream, storage);
  assert(output.size() == 64 && std::equal(output.begin(), output.begin() + 8, "TDINFO01"));
  output.clear();
  input = "RUN 9 100 0\n";
  usb_throughput::service(stream, storage);
  assert(output.size() == 32 && std::equal(output.begin(), output.begin() + 8, "TDERR001"));
  for (unsigned mode = 1; mode <= 5; ++mode) {
    output.clear();
    max_write = mode == 4 ? 1024 : 8192;  // exercise partial-write ownership
    input = "RUN " + std::to_string(mode) + " 100 0\n";
    usb_throughput::service(stream, storage);
    while (usb_throughput::state.sequence < 6 || usb_throughput::state.offset != 0)
      usb_throughput::service(stream, storage);
    fake_time += 100001;
    usb_throughput::service(stream, storage);
    assert(!usb_throughput::state.running);
    std::ofstream file(std::string(argv[1]) + "/mode-" + std::to_string(mode) + ".bin", std::ios::binary);
    file.write(reinterpret_cast<const char *>(output.data()), static_cast<std::streamsize>(output.size()));
  }
  input = "RUN 1 100 6000000\n";
  max_write = 8192;
  usb_throughput::service(stream, storage);
  const auto sent = output.size();
  usb_throughput::service(stream, storage);
  assert(output.size() == sent);  // pacing prevents a second immediate frame
  connected = false;
  usb_throughput::service(stream, storage);
  assert(!usb_throughput::state.running);
}
