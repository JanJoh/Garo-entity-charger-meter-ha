# Garo Entity Charger Meter

Custom Home Assistant integration for monitoring energy and power data from a Garo Entity Balance unit.
(Yeah yeah, 80% ChatGPT code...)

## What this is for
This is **only** to be able to pull data from a Garo Entity Balance Dynamic Load balancer to use as a grid consumption sensor in Home Assistant using the local Swagger API. 
Basically, it eliminates the need for any additional HAN/P1 reader if you already have the DLB connected to your main meter.

## What this is NOT for
Anything else. It has nothing to do with your EV Charger etc. 

## Features

- Local API access. No cloud requirement. No real limit on how often you can query data.
- Power, voltage, current sensors (L1, L2, L3)
- Total grid consumption (energy) compatible with Energy dashboard
- Configurable polling interval
- HTTPS with basic auth

## Installation (via HACS)

1. In HACS, go to **Integrations → Custom repositories**
2. Add this repo: `https://github.com/JanJoh/Garo-entity-charger-meter-ha`
3. Category: **Integration**
4. Install, then restart Home Assistant

## Configuration
- The requested IP is the IP of your Garo Entity Load balancer, **not** the IP of the EV Charger.

- You need to aquire the credentials for basic auth. These are on a sticker
on the physical device. Typically in the format 
Username **GaroLI-xxxxxxxxx**
Password **xxxx-xxxx-xxxx** (Please note that the password should be all lower case, regardless on what is printed on the sticker.

- The **Energy Total** sensor plugs nicely in as a grind consumption sensor. But please note that it may take a while for the new statistical sensor shows up in HA. 

