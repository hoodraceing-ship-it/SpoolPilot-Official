# SpoolPilot

SpoolPilot is a touchscreen and scale-based filament-management system for
[BamBuddy](https://github.com/maziggy/bambuddy). It combines barcode workflows,
NFC spool identification, weight tracking, inventory management, and Bambu Lab
AMS visibility in one ESPHome project.

This repository is the authoritative source for the matching SpoolPilot
firmware files. The console, scale, custom components, UI files, and assets are
versioned together so ESPHome never mixes local changes with an incompatible
upstream `main` branch.

## Supported hardware

### Console

- ELECROW CrowPanel Advance 5.0-inch ESP32-S3 display
- 800 × 480 capacitive touchscreen
- PN532 NFC reader in SPI mode
- BamBuddy server reachable over the local network or Tailscale

### Scale

- Seeed Studio XIAO ESP32-S3
- HX711 load-cell amplifier
- 5 kg straight-bar load cell
- PN532 NFC reader in SPI mode

## Features

- Barcode-based filament identification and catalog creation
- BamBuddy internal inventory or Spoolman inventory support
- NFC tagging, scanning, linking, and unlinking
- Live spool weight, tare, calibration, and quick weight updates
- Scale-to-console HTTP push integration
- AMS, AMS HT, virtual tray, and external spool visibility
- AMS drying start/stop controls on supported printers and firmware
- CrowPanel touchscreen workflows and status indicators
- Wi-Fi reconnect tuning and fallback access points
- Local custom components pinned to the same repository version

## Canonical firmware files

| Device | File |
|---|---|
| CrowPanel console | `spoolpilot_console_crowpanel.yaml` |
| XIAO ESP32-S3 scale | `spoolpilot_scale_xiao_esp32s3.yaml` |

Do not use old `spoolbuddy_*` configuration files from previous downloaded
folders with these components. The two files above are the supported entry
points for this repository.

## Quick start

1. Clone or download the entire repository.
2. Copy `secrets.yaml.example` to `secrets.yaml`.
3. Enter your Wi-Fi, BamBuddy, OTA, and ESPHome API values.
4. Review the console address in `spoolpilot_scale_xiao_esp32s3.yaml`.
5. Connect the device by USB for its first flash.

Windows PowerShell console flash:

```powershell
py -m esphome run .\spoolpilot_console_crowpanel.yaml --device COM7
```

Windows PowerShell scale flash:

```powershell
py -m esphome run .\spoolpilot_scale_xiao_esp32s3.yaml --device COM6
```

COM port numbers are examples. Use the port shown in Windows Device Manager.

Full instructions are in:

- [Installation](docs/INSTALL.md)
- [Wiring](docs/WIRING.md)
- [Updating](docs/UPDATING.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Network behavior

The console talks directly to BamBuddy. The scale does not contact BamBuddy;
it pushes weight and NFC events to the console on port `8080`. The scale file
currently uses `http://192.168.1.168` for the console because that is the
reserved address of the original SpoolPilot installation. Change it if your
console uses another address, and reserve that address in your router.

## Secrets and security

`secrets.yaml` is ignored by Git and must never be committed. The example file
contains placeholders only. SpoolPilot uses the BamBuddy API key you create in
BamBuddy and the ESPHome encryption/OTA credentials you provide locally.
The repository does not contain Bambu cryptographic key material. Protected
Bambu MIFARE decoding is disabled unless an authorized device owner supplies a
key locally; reusable NTAG workflows do not require one.

## Credits

SpoolPilot is inspired by and built from
[ESPoolBuddy](https://github.com/CSchlipp/espoolbuddy) by CSchlipp. It expands
that project with the ELECROW CrowPanel 5-inch interface, barcode workflows,
custom scale hardware, additional BamBuddy integration, and SpoolPilot-specific
UI and reliability changes.

SpoolPilot also integrates with
[BamBuddy](https://github.com/maziggy/bambuddy) by maziggy.

Powered by ESPoolBuddy and expanded into a complete filament-management
platform.

## License

SpoolPilot retains ESPoolBuddy's
[GNU Affero General Public License v3.0](LICENSE). See [NOTICE.md](NOTICE.md) for
attribution and modification information.
