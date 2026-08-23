# Troubleshooting

## `esphome.exe` is blocked by Application Control

Run ESPHome through Python:

```powershell
py -m esphome version
py -m esphome run .\spoolpilot_console_crowpanel.yaml --device COM7
```

## `set_ams_drying` undefined reference

This means the UI/header and C++ implementation came from different versions.
The canonical repository contains the implementation. Confirm it exists:

```powershell
Select-String -Path ".\components\bambuddy_api\bambuddy_api.cpp" -Pattern "void BambuddyAPIComponent::set_ams_drying"
```

Then clean and rebuild the canonical configuration.

## `backlight_id` is invalid or required

This also indicates mixed component versions. Use
`spoolpilot_console_crowpanel.yaml` from the same release as the `components`
folder and run `esphome clean` before compiling.

## Scale cannot resolve the console hostname

Use the console's numeric reserved IPv4 address in
`spoolpilot_scale_xiao_esp32s3.yaml`. The default is:

```yaml
console_url: "http://192.168.1.168"
```

Windows failing to resolve `spoolpilot-console.local` does not prove the device
is offline. Test the numeric address instead.

## Console Wi-Fi disconnects

- Use 2.4 GHz Wi-Fi.
- Keep the panel away from large metal surfaces and USB 3 interference.
- Reserve its DHCP address in the router.
- Confirm `power_save_mode: none`, `fast_connect: true`, and `output_power:
  20.5dB` remain in the console configuration.
- Power the CrowPanel with a stable USB supply and cable.

Console logs:

```powershell
py -m esphome logs .\spoolpilot_console_crowpanel.yaml --device COM7
```

## Device powers on but no COM port appears

- Use a known data-capable USB cable.
- Try another USB port.
- Check Device Manager for CH340K or USB Serial Device.
- For the XIAO ESP32-S3, enter bootloader mode using its BOOT/RESET procedure,
  then check Device Manager again.

## Captive portal warning

The canonical configurations include fallback access points. Ensure
`fallback_hotspot_password` exists in `secrets.yaml`.
