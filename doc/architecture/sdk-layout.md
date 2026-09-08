---
type: architecture
title: SDK Layout and Documentation
created: 2026-09-08
tags:
  - sdk
  - documentation
related:
  - '[[System-Overview]]'
  - '[[Protocol-V2]]'
---

# SDK layout and documentation

The public Python distribution is **thingdone-daq**, imported as
**thingdone_daq**. Its source, packaging, examples, and tests remain together
under `daq_api/`. The public facade remains `ThingDAQ`.

The hardware product, USB identity, C++ namespaces, calibration file format,
and protocol schema identifiers retain their existing ThingDAQ names. Python
package naming does not change the device protocol or saved-data compatibility.

`protocol/` is the language-independent contract: canonical JSON and binary
golden fixtures belong here. Each future language SDK should have its own
source, build metadata, tests, examples, release version, and package-registry
name, and verify encoding/decoding against those shared fixtures. Python and
firmware happen to be version 1.1.0; future SDK releases need not track firmware
version numbers.

The existing Python API reference is the current documentation landing page.
For a future website, use separate `/python/`, `/rust/`, etc. sections with
language-specific quickstarts, installation, examples, API references, and
version selectors. Keep hardware safety and the wire protocol in shared
sections and link to them from each SDK. Add a language section only when that
SDK exists. A static site can consume this repository's Markdown and generated
API references; deployment and a domain are not required for the PyPI release.

When a website is available, update `project.urls.Documentation` in the Python
`pyproject.toml`. Its current GitHub link becomes publicly readable when the
repository does.
