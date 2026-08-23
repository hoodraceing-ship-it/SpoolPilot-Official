# SpoolPilot v0.1.0

This is the first unified SpoolPilot source release.

It combines the ELECROW CrowPanel Advance 5.0-inch console, Seeed Studio XIAO
ESP32-S3 scale, HX711 support, PN532 NFC readers, barcode workflow, custom LVGL
interface, and matching BamBuddy component code in one versioned repository.

Important fixes include the missing AMS drying implementation, live drying
status parsing, corrected XIAO pin assignments, local component pinning, and
Wi-Fi reliability settings.

Use only these entry files:

- `spoolpilot_console_crowpanel.yaml`
- `spoolpilot_scale_xiao_esp32s3.yaml`

See `docs/INSTALL.md` and `docs/WIRING.md` before flashing.
