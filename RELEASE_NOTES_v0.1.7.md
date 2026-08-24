# SpoolPilot v0.1.7

This release fixes weight-screen flashing at the source instead of forcing a
display-wide synchronization delay.

- The console no longer rewrites unchanged weight labels every 400 ms.
- Weight and stability labels use compact dirty rectangles that fit within one
  LVGL draw-buffer flush.
- The scale reports whole-gram changes after stronger median and moving-average
  filtering.
- PN532 behavior is unchanged; testing already ruled it out as the source of
  the scale drift.
