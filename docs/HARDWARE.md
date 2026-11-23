# Which device?

**Recommended: Raspberry Pi 5** (2 GB of memory or more) with Home Assistant OS. This is the device TV7 Player is developed and tested on.

| Device | Suitable? |
|---|---|
| Raspberry Pi 5 | **yes**, recommended |
| Raspberry Pi 4, Pi 400, CM4 | probably, not tested |
| Raspberry Pi CM5 | probably (like the Pi 5), not tested |
| Mini PC with Intel or AMD graphics and an HDMI port | probably, not tested |
| Raspberry Pi 3 and older, Pi Zero | no, too slow |
| Home Assistant Green | no, its HDMI port shows no picture |
| Virtual machine, NAS | no, there is no real HDMI output |

## Tips for the Raspberry Pi 5
- **Memory:** 2 GB is enough; more brings no benefit for TV7.
- **Power and cooling:** use the official power supply and the active cooler (or a case with a fan).
- **HDMI port:** use the port next to the power connector (`HDMI-A-1`), or choose the port in the settings.
- **Network:** a network cable gives the most reliable picture.

## Already running Home Assistant on another device?
TV7 Player needs a device with an HDMI output next to the TV. If your Home Assistant runs elsewhere (Home Assistant Green, a virtual machine, a NAS), set up a Raspberry Pi 5 with Home Assistant OS and TV7 Player at the TV. It is a Home Assistant of its own: you operate TV7 there (sidebar, TV remote), and its automations can control the player.

## Devices marked "not tested"
TV7 Player contains the support for these devices, but nobody has tried it yet. If you have one, please try it and report the result in an [issue](https://github.com/SebiGo/tv7/issues) (Settings > Copy support info).
