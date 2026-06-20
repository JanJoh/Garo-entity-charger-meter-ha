# GARO Entity Charger Meter

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/JanJoh/Garo-entity-charger-meter-ha)](https://github.com/JanJoh/Garo-entity-charger-meter-ha/releases)

Home Assistant integration for GARO EV chargers with a built-in energy meter (Entity Balance / Dynamic Load Balancer). Polls the device's local REST API — no cloud, no GARO account required.

> Mostly LLM-generated code. It works, but don't expect miracles.

---

## What it does

Exposes the GARO charger's built-in energy meter and charging state as Home Assistant sensors. Primary use case: use the **Charger Imported Energy** sensor as a grid consumption source in the HA Energy dashboard when the GARO unit is connected to your main meter.

Also surfaces EV charging state, CP/PP signal levels, temperatures, and device diagnostics.

---

## Requirements

- GARO EV charger with Entity Balance / DLB firmware exposing a local REST API
- BasicAuth credentials (printed on a sticker on the physical device)
  - Username: `GaroCU-xxxxxxxxx`
  - Password: `xxxx-xxxx-xxxx` — **enter in lowercase**, regardless of what the sticker says

---

## Installation

### HACS (recommended)

1. HACS → **Custom repositories** → add `https://github.com/JanJoh/Garo-entity-charger-meter-ha` as type **Integration**
2. Install **GARO Entity Charger Meter**
3. Restart Home Assistant
4. Settings → Devices & Services → **Add integration** → search for *GARO*

### Manual

Copy `custom_components/garo_entity_charger_meter/` into your HA `config/custom_components/` directory and restart.

---

## Configuration

| Field | Default | Description |
|---|---|---|
| Host | — | IP address of the GARO unit |
| Username / Password | — | BasicAuth credentials from the device sticker |
| Fast poll interval | 15 s | How often to fetch live data (power, current, charging state) |
| Slow poll interval | 300 s | How often to fetch static data (firmware, network, temperatures) |
| Ignore TLS errors | off | Skip certificate validation (useful for self-signed certs) |
| Use HTTP | off | Use plain HTTP instead of HTTPS |
| Phase sensors | on | Enable per-phase current and voltage sensors |
| Line voltages | off | Enable L1-L2, L2-L3, L3-L1 voltage sensors |

Intervals can be changed after setup via **Settings → Devices & Services → GARO → Configure**.

---

## Sensors

### Energy & power (fast poll)

| Sensor | Unit | Notes |
|---|---|---|
| Charger Imported Energy | kWh | Use this in the HA Energy dashboard |
| Charger Active Power | W | |
| Charger Total Current | A | Sum of L1+L2+L3 |
| Charger Average Voltage | V | Average of L1/L2/L3 |
| Charger L1/L2/L3 Current | A | Enabled via phase sensors option |
| Charger L1/L2/L3 Voltage | V | Enabled via phase sensors option |
| Charger L1-L2 / L2-L3 / L3-L1 Voltage | V | Enabled via line voltages option |

### EV charging (fast poll)

| Sensor | Notes |
|---|---|
| CP State | IEC 61851 state derived from CP voltage: *No vehicle connected*, *Vehicle connected*, *Charging*, etc. Enabled by default. |
| Charging State | Raw GARO charging state code (e.g. `B2`) |
| CP Signal Max / Min | Control Pilot voltage in volts |
| PP Level | Proximity Pilot voltage — indicates cable type/capacity |

### Diagnostics & device info (slow poll, disabled by default)

| Sensor | Notes |
|---|---|
| Charger CPU / Board Temperature | °C |
| Firmware Version | Application firmware |
| Device ID | Serial number (e.g. `GaroCS-...`) |
| Unit ID | Hardware unit ID containing MAC address |
| Network Interface | Active network interface (`Ethernet`, `wlan0`, etc.) |
| IP Address | Current IP of the device |
| Wi-Fi SSID / Signal | Only populated when connected via Wi-Fi |
| SIM ICCID / SIM Operator | Only populated on LTE-equipped units |
| PLC Firmware Version | Power-line communication module firmware |
| PLC Zero Cross | Zero-crossing detection state |
