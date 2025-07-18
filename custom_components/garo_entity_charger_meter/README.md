# Garo Entity Charger Meter

This is a custom Home Assistant integration that polls a Garo EV Charger over HTTPS using basic authentication to read electricity meter values from a HAN port.

## Features

- Reports power, energy, current (per phase), and voltage (per phase)
- Energy sensor supports Home Assistant Energy Dashboard (Wh)
- Configurable polling interval
- Secure HTTPS with optional self-signed certificate support

## Installation via HACS

1. Go to HACS > Integrations > Custom Repositories
2. Add this repository: `https://github.com/JanJoh/Garo-entity-charger-meter-ha`
3. Select category: `Integration`
4. Install and restart Home Assistant

## Configuration

Go to Settings > Devices & Services > Add Integration > Garo Entity Charger Meter and enter:

- Host: IP or hostname of the device
- Username/Password: For basic authentication
- Polling interval (default: 15 min)

## License

MIT License