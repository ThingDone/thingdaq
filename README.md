# teensy_daq

This project is going to run on a teensy 4.0.

We want it make a firmware based DAQ we can use on multiple projects for different customers. The idea is we are going to have python scripts that want to read data from live systems. 

We want to support the following:
1. Dual ADCs running interleaved on pins A0 and A1 at 1MHz. We want them running via DMA interlaved on some rotating buffers. 
2. 8 pins (accessible from headers on a breadboard) read out at 4MHz. Ideally we want to read this out via dma or potentially some interrupt driven system.
3. We default to sending information, but we need a command set to enable/disable different functionality
4. We want a native python api for detecting and controlling our teensy daq
5. We will support a test mode that sends out patterns for validating that we are reassembling the data properly.

Data format:
In the future, we may accept some commands, but for now we are encapselating the data we send into messages. Here is the format:

*Entire set of message must be a multiple of 512 bytes*
Header 4bytes - 0xdeadbeef
Type 2 bytes  - (0->ADC, 1->GPIO)
Size 2 bytes  - size of payload
Time 4 bytes  - 8x microseconds for resynchronization
payload  0->size byte
checksum 4bytes - Standard Adler-32

Ideally it will show up as a serial port in windows, and we can have python read out the different packets of information. It can then reassemble it according to time, and also determine if some time slice has dropped.

The command format should be similar but do not have to be multiples of 512 byte:
Header 4bytes - 0xdeadbeef
Type 2 bytes  - Command Type
Size 2 bytes  - size of payload
payload  0->size byte
checksum 4bytes - Standard Adler-32

# Testing
We will leaverage /home/bill/agents/fw_experiments/docs/guides/new-firmware-projects.md for building and testing our project here.

We want to evaluate the following:
1. Test that our firmware works and can be carefully controlled via python.
2. We will ensure our python api is well documented.
3. We will have a benchmark on how much usb bandwidth is used.
4.

## Repository layout

- `firmware/` contains the Teensy 4.0 sketch boundary, portable C++ modules,
  local build tooling, and firmware-focused host tests.
- `daq_api/` contains the installable `teensy_daq` Python package in a
  `src/` layout and its test suite.
- `doc/` contains structured architecture, protocol, decision, reference, and
  result artifacts. Start with `doc/README.md` and
  `doc/architecture/System-Overview.md`.

Generated builds, captures, virtual environments, benchmark scratch data,
credentials, and language-tool caches are ignored. Small deterministic test
fixtures remain tracked under the firmware or Python test trees.

Every Markdown artifact under `doc/` must begin with YAML front matter
containing `type`, `title`, `created`, `tags`, and `related`, and must use
`[[Wiki-Links]]` for related project documents.
