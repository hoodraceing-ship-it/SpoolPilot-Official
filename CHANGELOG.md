# Changelog

All notable SpoolPilot changes are documented here.

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
