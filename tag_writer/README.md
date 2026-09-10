# SpoolPilot Tag Writer

Windows desktop application for searching the public Bambu Lab RFID Library and writing a selected filament profile to a compatible write-once FUID tag with a Proxmark3 Easy.

## Safety model

- Requires five consecutive clean MIFARE Classic 1K / SAK 08 identifications.
- Rejects RFID collisions and unstable BCC responses.
- Inspects all sectors with both blank and selected-profile keys.
- Recognizes fresh, partially programmed, and already-complete selected-profile tags.
- Writes and verifies ordinary data before changing keys or the UID.
- Tests sector 15 before protecting the remaining sectors.
- Uses one persistent Proxmark client session per phase, avoiding Windows COM-port churn.
- Retries only a Windows COM-port-open failure; it never blindly retries an ambiguous write.
- Saves a recovery record before any protected trailer or UID operation.
- Writes the manufacturer block only after all data and protected sectors verify.
- Performs a complete final readback before reporting success.

## Requirements

- Windows 10 or 11
- RRG/Iceman Proxmark3 Windows bundle already flashed and working
- Compatible MIFARE Classic 1K write-once FUID tag
- Internet access when updating the filament library or downloading a selected entry

## Install

Run `Install-SpoolPilotTagWriter.ps1` from PowerShell. It downloads the standalone Windows app, verifies its SHA-256 checksum, installs it under `%LOCALAPPDATA%\SpoolPilotTagWriter`, and creates a desktop shortcut. Python is not required.

The application automatically finds recent `rrg_other-*` Proxmark packages under Downloads and detects USB serial COM ports. Both can also be selected manually.

Version 0.4.2 replaces the updater with a logged, transactional installer. It waits for the running EXE to close, verifies the staged replacement, keeps a rollback copy, starts the new version, and restores the old copy if the new app exits immediately. Update logs are saved beside the reader logs. This version also fixes Proxmark command-file launching from paths containing spaces and adds an **Open Logs Folder** button beside **Diagnose Reader / Tag**.

## Library behavior

The app reads the current public `queengooborg/Bambu-Lab-RFID-Library` Git tree and caches a searchable catalog. Thousands of UID duplicates are collapsed into one deterministic dump per material/product/color. Only the selected dump and key file are downloaded.

## Recovery

Raw Proxmark output is stored under `%LOCALAPPDATA%\SpoolPilotTagWriter\logs`. A JSON recovery record is stored before writing under `%LOCALAPPDATA%\SpoolPilotTagWriter\recovery` and updated after every irreversible stage.

If a protected sector contains data from another profile or cannot be authenticated with either blank or selected-profile keys, the app stops before changing the UID. Cheap or counterfeit tags and unstable RF coupling can still fail; the safety checks reduce avoidable tag loss but cannot guarantee defective hardware.
