# SpoolPilot Wiring

Disconnect USB power before changing wiring. Both PN532 readers must be set to
SPI mode using the module's switches or jumpers.

## XIAO ESP32-S3 scale

### HX711 to XIAO

| HX711 | XIAO ESP32-S3 |
|---|---|
| VCC | 3.3V |
| GND | GND |
| DT / DOUT | D9 / GPIO8 |
| SCK / CLK | D10 / GPIO9 |

### PN532 to XIAO

| PN532 | XIAO ESP32-S3 |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SCK | D8 / GPIO7 |
| MISO | D7 / GPIO44 |
| MOSI | D6 / GPIO43 |
| SS / CS | D3 / GPIO4 |
| IRQ | D1 / GPIO2 |

### Load cell to HX711

Load-cell wire colors are not universal. Follow the markings supplied with the
load cell. A common four-wire arrangement is:

| Load-cell function | Common color | HX711 |
|---|---|---|
| Excitation positive | Red | E+ |
| Excitation negative | Black | E- |
| Signal positive | Green | A+ |
| Signal negative | White | A- |

Verify the load-cell documentation before applying power. If the weight moves
in the wrong direction, swap A+ and A- rather than changing E+ and E-.

## ELECROW CrowPanel console PN532

| PN532 | CrowPanel ESP32-S3 |
|---|---|
| VCC | 3.3V |
| GND | GND |
| SCK | GPIO5 |
| MOSI | GPIO6 |
| MISO | GPIO4 |
| SS / CS | GPIO19 |

The console uses PN532 polling and does not require an IRQ connection.

GPIO19 produces an ESPHome USB-Serial-JTAG warning. The CrowPanel uses its
CH340K USB serial interface for flashing, so the warning is expected with this
wiring.
