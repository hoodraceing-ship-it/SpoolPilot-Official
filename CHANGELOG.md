# Changelog

All notable SpoolPilot changes are documented here.

## [0.1.7] - 2026-08-23

### Fixed

- Update the scale labels only when their visible value or state changes.
- Reduce the live weight redraw from the full 800-pixel width to a compact area.
- Remove the per-flush VSYNC wait that could expose intermediate LVGL chunks.
- Strengthen the HX711 median and moving-average filters and suppress motion
  below one gram.

## [0.1.6] - 2026-08-23

### Fixed

- Add a SpoolPilot MIPI-RGB driver override based on ESPHome 2026.7.4.
- Stop restarting the CrowPanel RGB DMA stream on every component loop.
- Synchronize framebuffer writes to VSYNC to prevent live weight-label updates
  from splitting old and new pixels across the same visible frame.

## [0.1.5] - 2026-08-23

### Fixed

- Keep Tare available even when a noisy or mechanically drifting scale never
  reaches the stability threshold.
- Clearly warn when a forced tare is captured from a moving reading instead of
  silently storing a potentially drifting zero point.

## [0.1.4] - 2026-08-23

### Fixed

- Repeat the scale's settled-state notification so HTTP job coalescing cannot
  permanently leave the console in `Settling - Tare disabled`.
- Move the 800x480 LVGL draw buffer from slower PSRAM to a recommended 12%
  internal-RAM buffer to reduce tearing during live screen updates.

## [0.1.3] - 2026-08-23

### Fixed

- Reject tare commands while the HX711 reading is still settling.
- Require three continuous seconds without a significant weight change before
  declaring the scale stable.
- Disable the Scale-tab Tare button and show a clear settling message until the
  reading is safe to use as the zero point.

## [0.1.2] - 2026-08-23

### Fixed

- Prevent repeated `esp_task_wdt_reset(): task not found` errors when ESP-IDF
  has not registered the console HTTP worker with the task watchdog.
- Keep normal ESP-IDF idle-task watchdog coverage active while treating the
  custom HTTP-worker subscription as optional.

## [0.1.1] - 2026-08-23

### Changed

- Wi-Fi remains fully awake when the console display sleeps.
- BamBuddy heartbeat and printer polling keep their normal cadence during
  display sleep.
- Normal AP scanning replaces `fast_connect` so mesh and multi-AP networks can
  select the strongest BSSID.
- Console and scale restart after five continuous minutes without Wi-Fi, giving
  the ESP32 radio a clean recovery from a stuck association.
- The previous Wi-Fi-off sleep option is disabled in the console interface.
- Scale RSSI diagnostics now update every 10 seconds.

## [0.1.0] - 2026-08-23

### Added

- Canonical ELECROW CrowPanel Advance 5.0-inch console configuration.
- Canonical Seeed Studio XIAO ESP32-S3 scale configuration.
- HX711 support on D9/GPIO8 and D10/GPIO9.
- PN532 scale wiring with MISO moved to D7/GPIO44.
- XIAO status LED support on the correct GPIO21 user LED.
- Barcode catalog and spool onboarding interface.
- AMS drying start/stop API implementation and live drying-state parsing.
- Scale weight and NFC push integration on console port 8080.
- Installation, wiring, update, and troubleshooting documentation.
- GitHub Actions compile validation for both canonical firmware targets.

### Changed

- Both devices now use the matching local custom components from this
  repository instead of importing an unpinned upstream `main` branch.
- Console Wi-Fi uses `power_save_mode: none`, fast connection mode, maximum
  configured transmit power, and a fallback access point.
- Scale defaults to the console's reserved LAN address instead of relying on
  unreliable `.local` name resolution.
- Removed inherited hardcoded cryptographic material from the NFC component.
- Protected Bambu MIFARE decoding is now opt-in with a locally supplied key;
  reusable NTAG scanning and writing continue to work without it.

### Fixed

- Missing `BambuddyAPIComponent::set_ams_drying(int, bool)` linker symbol.
- Missing AMS drying job handler.
- Missing `dry_time` and `dry_status` parsing.
- Incompatible `backlight_id` configuration from mismatched component versions.
- Invalid inherited NFC `!extend` configuration on the XIAO scale.
