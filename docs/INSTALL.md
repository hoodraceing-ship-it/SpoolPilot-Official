# Installation

## Requirements

- Windows 10 or Windows 11
- Python with ESPHome installed
- Git, or a downloaded SpoolPilot source ZIP
- ELECROW CrowPanel Advance 5.0-inch console
- Seeed Studio XIAO ESP32-S3 scale controller
- A running BamBuddy server

## 1. Prepare the repository

Clone the repository or download and extract the release source archive. Open
PowerShell in the extracted folder.

Create your secrets file:

```powershell
Copy-Item .\secrets.yaml.example .\secrets.yaml
notepad .\secrets.yaml
```

Fill in every placeholder. Do not upload or commit `secrets.yaml`.

Protected Bambu MIFARE tag decoding is disabled by default. The repository does
not distribute Bambu cryptographic material. Reusable NTAG identification and
writing continue to work without it. Device owners who are independently
authorized to use a key can store it only in `secrets.yaml` and reference it
with the optional `bambu_master_key` setting under `bambuddy_nfc`.

The BamBuddy URL must include the scheme and port, for example:

```yaml
bambuddy_backend_url: "http://192.168.1.177:8001"
```

## 2. Verify the COM ports

```powershell
Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Name
```

The CrowPanel normally appears as a CH340/CH340K serial device. The XIAO may
appear as a USB Serial Device.

## 3. Flash the console

```powershell
py -m esphome run .\spoolpilot_console_crowpanel.yaml --device COM7
```

## 4. Reserve the console address

Reserve the console's IPv4 address in the router. The original SpoolPilot
installation uses `192.168.1.168`.

## 5. Configure and flash the scale

Open `spoolpilot_scale_xiao_esp32s3.yaml` and update `console_url` if the
console does not use `192.168.1.168`.

```powershell
py -m esphome run .\spoolpilot_scale_xiao_esp32s3.yaml --device COM6
```

## 6. Confirm the scale connection

```powershell
Test-NetConnection 192.168.1.168 -Port 8080
```

`TcpTestSucceeded` should be `True` while the console is powered and connected.

## 7. Calibrate

Power the scale with the platform empty, tare it, then calibrate it using a
known reference weight. A 500 g or 1 kg calibration weight is suitable for the
5 kg load cell.
