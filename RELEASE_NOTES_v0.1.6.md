# SpoolPilot v0.1.6

This release replaces the CrowPanel's built-in ESPHome 2026.7.4 MIPI-RGB
component with a matching local override designed for the SpoolPilot console.

- Framebuffer writes wait for the beginning of a new display frame.
- The RGB DMA engine is no longer restarted continuously in the component loop.
- Live scale values can redraw without mixing the previous and next number in
  one scanned frame.

The driver override is limited to the console. The scale version is bumped so
both device logs continue to identify the matching SpoolPilot release.
