# SpoolPilot v0.1.1

This release focuses on reliable always-online operation for the CrowPanel
console and XIAO ESP32-S3 scale.

## Highlights

- Keeps console Wi-Fi at full power while the display sleeps.
- Keeps BamBuddy heartbeat and printer polling at their normal cadence.
- Disables the previous Wi-Fi-off sleep option.
- Uses normal AP scanning for better mesh and multi-access-point selection.
- Reboots after five continuous minutes without Wi-Fi to recover a stuck radio.
- Updates scale RSSI every 10 seconds.

Both canonical YAML files were validated with ESPHome 2026.7.4.
