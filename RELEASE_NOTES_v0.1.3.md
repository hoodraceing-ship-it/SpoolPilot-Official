# SpoolPilot v0.1.3

This release prevents bad tare offsets caused by taring while the HX711 filter
is still converging.

- Tare is available only after three continuous seconds of stable readings.
- The Scale tab shows `Settling - Tare disabled` until the reading is ready.
- Console, scale, and non-UI tare entry points all enforce the same rule.

If the scale never becomes stable while empty and untouched, inspect its analog
wiring, power, and mechanical mounting before attempting calibration.
