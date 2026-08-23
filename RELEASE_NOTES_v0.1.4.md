# SpoolPilot v0.1.4

This maintenance release addresses the two problems observed during live scale
testing:

- The XIAO scale now repeats a stable reading once per second while settled.
  This ensures the console receives `stable=true` even when the first update is
  coalesced with an already-pending weight upload, allowing Tare to become
  available normally.
- The CrowPanel console now uses a 12% LVGL draw buffer. On an ESP32-S3 with
  PSRAM this keeps the draw buffer in faster internal RAM and reduces visible
  tearing during frequent weight-label redraws.

The stability guard remains in place: Tare is disabled while the physical
reading is genuinely moving so an incorrect zero point cannot be stored.
