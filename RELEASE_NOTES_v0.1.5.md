# SpoolPilot v0.1.5

The Scale-tab Tare control is now always available whenever a scale is
connected. A settled reading remains preferred, but a noisy HX711 or mechanical
mount can no longer leave the control disabled indefinitely.

When Tare is pressed while the reading is still moving, SpoolPilot captures the
current filtered reading and displays a warning that the zero point may drift.
This restores manual control without concealing the underlying hardware noise.
