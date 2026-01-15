# CJA SKYFARMS Smart Farm Control Project

## Overview

This project is a system that controls the smart farm environment of CJA SKYFARMS using Python.
It integrates and manages various environmental control devices and sensors, such as fans, air circulators, and nutrient pumps,
and allows easy control through a Tkinter-based GUI.

## Folder Structure

```
cja-skyfarms-project/
├── main.py                       # Main execution file (UI and overall control)
├── controllers/                  # Environmental control modules
│   ├── DCFan.py                  # DC fan control class
│   ├── AirCirculator.py          # Air circulator control class
│   └── NutrientPump.py           # Nutrient pump control class (example)
├── sensors/                      # Sensor data collection modules
│   └── SensorReader.py           # Sensor data reading
├── utils/                        # Utility functions and common code
│   └── logger.py                 # Logging and other utilities
├── requirements.txt              # Python package list
├── README.md                     # Project documentation
└── data/                         # Data and log storage folder
    └── logs/
```

## Installation and Usage

1. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   bash <(curl -sL https://raw.githubusercontent.com/node-red/linux-installers/master/deb/update-nodejs-and-nodered)
   pip3 install minimalmodbus
   ```

2. **Run the program**

   ```bash
   python3 main.py
   ```

3. **External integrations (e.g., Node-RED)**

   * You can import a separate `flows.json` file into Node-RED to integrate the system.

## Key Features

* Control of environmental devices such as fans, air circulators, and nutrient pumps
* Real-time sensor data monitoring
* Easy control via GUI
* Expandable modular structure

## Contributing and Inquiries

* Please submit issues and pull requests via the GitHub repository.
