# SpoolPilot v0.1.2

This maintenance release fixes repeated ESP-IDF task-watchdog errors in the
serial log after boot.

The console HTTP worker now calls `esp_task_wdt_reset()` only when its own
watchdog registration succeeded. The standard ESP-IDF idle-task watchdog
remains enabled, and scale-mode behavior is unchanged.
