# Updating SpoolPilot

SpoolPilot releases keep the console, scale, UI, and components on the same
version. Replace the complete repository folder when updating; do not copy a
single YAML or component from another branch.

## Safe Windows update

1. Save a copy of `secrets.yaml` outside the repository folder.
2. Download or pull the desired tagged release.
3. Restore `secrets.yaml`.
4. Clean the old ESPHome build cache.
5. Compile and flash the canonical entry file.

Console:

```powershell
py -m esphome clean .\spoolpilot_console_crowpanel.yaml
py -m esphome run .\spoolpilot_console_crowpanel.yaml --device COM7
```

Scale:

```powershell
py -m esphome clean .\spoolpilot_scale_xiao_esp32s3.yaml
py -m esphome run .\spoolpilot_scale_xiao_esp32s3.yaml --device COM6
```

Run each PowerShell command separately. Do not paste `Select-String` or another
command onto the end of the ESPHome command.
