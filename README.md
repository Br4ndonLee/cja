# CJA SKYFARMS Plant Factory Control Project

## Overview

This project is a plant factory control system for the CJA SKYFARMS plant factory, built with **Python** and **Node-RED** on a Raspberry Pi.

It integrates and manages various environmental control devices and sensors (fans, air circulators, LEDs, UV-C, nutrient pumps, EC/pH sensors, temperature/humidity sensors, etc.), and provides an easy-to-use **Node-RED–based GUI** for monitoring and control.

The system is designed to be:

- **Modular** – each actuator/sensor has its own controller or script  
- **Extensible** – easy to add new devices and logic  
- **Raspberry Pi–friendly** – uses hardware and libraries commonly available on RPi

---

## Folder Structure

```text
cja-skyfarms-project/
├── main.py                           # Main execution file (entry point, UI and overall control)
├── controllers/                      # Environmental control modules
│   ├── FanController.py              # DC fan control
│   ├── AirCirculatorController.py    # Air circulator control
│   ├── LEDController.py              # LED control
│   ├── UVController.py               # UV-C control
│   └── PumpController.py             # Nutrient pump control
├── sensors/                          # Sensor data collection modules
│   ├── EC_pH.py                      # EC, pH sensor data collection
│   ├── Temp_humi.py                  # Temperature and humidity data collection
│   ├── EC_pH_log.csv                 # EC, pH sensor log
│   ├── Temp_humi_log.csv             # Temperature and humidity log
│   └── Solution_input_log.csv        # A/B and acid solution input log
├── data/                             # Additional data / log storage
│   └── logs/                         # (Reserved for log files)
├── node-red/                         # Node-RED configuration and project files (synced from ~/.node-red)
│   └── projects/
│       └── cja-skyfarms/
│           ├── flows.json            # Node-RED flow for this project
│           ├── package.json          # Node-RED project metadata & dependencies
│           ├── README.md             # Node-RED project documentation
│           └── ui-media/             # Dashboard / UI media assets (if any)
├── requirements.txt                  # Python package list
└── README.md                         # This document
````

> **Note**
> The `node-red/` directory is periodically synchronized from `~/.node-red` on the Raspberry Pi.
> Files like `flows_<hostname>_cred.json` (credentials) are intentionally excluded from version control.

---

## Installation

### 1. Python environment

Install Python dependencies:

```bash
cd ~/Work/cja-skyfarms-project
pip install -r requirements.txt
pip3 install minimalmodbus
```

> Use a virtual environment if needed:
>
> ```bash
> python -m venv .venv
> source .venv/bin/activate
> pip install -r requirements.txt
> ```

---

### 2. Node-RED (on Raspberry Pi / Debian-based systems)

Install or update Node.js and Node-RED using the official installer:

```bash
bash <(curl -sL https://raw.githubusercontent.com/node-red/linux-installers/master/deb/update-nodejs-and-nodered)
```

Enable and start Node-RED as a service (optional but recommended):

```bash
sudo systemctl enable nodered.service
sudo systemctl start nodered.service
```

You can also start it manually:

```bash
node-red-start
```

Default Node-RED editor URL:

* `http://<raspberrypi-hostname>:1880/`

---

### 3. (Optional) Camera & Video Streaming Setup

If you want to monitor the plant factory visually, you can use a USB camera + `fswebcam` and **mjpg-streamer**.

#### 3.1. Video4Linux utilities

```bash
sudo apt update
sudo apt install v4l-utils
```

Check connected cameras:

```bash
v4l2-ctl --list-devices
```

Check supported formats and resolutions:

```bash
v4l2-ctl --list-formats-ext -d /dev/video0
```

View all camera settings:

```bash
v4l2-ctl --all -d /dev/video0
```

#### 3.2. fswebcam (simple still images)

```bash
sudo apt install fswebcam

# Capture a test image (640x480)
fswebcam -d /dev/video0 -r 640x480 test.jpg
```

#### 3.3. mjpg-streamer (HTTP video streaming)

Install build tools:

```bash
sudo apt install cmake libjpeg8-dev gcc g++ git
```

Download and build mjpg-streamer:

```bash
cd ~
git clone https://github.com/jacksonliam/mjpg-streamer.git
cd mjpg-streamer/mjpg-streamer-experimental

make
sudo make install
```

Run basic streaming (port 8080):

```bash
./mjpg_streamer \
  -i "input_uvc.so -d /dev/video0 -r 640x480 -f 30" \
  -o "output_http.so -p 8080 -w www"
```

HD streaming example:

```bash
./mjpg_streamer \
  -i "input_uvc.so -d /dev/video0 -r 1280x720 -f 15" \
  -o "output_http.so -p 8080 -w www"
```

Then open:

* `http://<raspberrypi-hostname>:8080/`

---

## Usage

### 1. Start Node-RED

```bash
node-red-start
```

Open the editor in a browser:

* `http://<raspberrypi-hostname>:1880/`

If you are not using the Node-RED Project Mode mapped directly to this repo, you can:

1. Open Node-RED editor
2. Import `node-red/projects/cja-skyfarms/flows.json`
3. Deploy the flows

---

### 2. Run the Python control program

From the project root:

```bash
cd ~/Work/cja-skyfarms-project
python main.py
```

> Depending on your setup, `main.py` may start the UI and begin interacting with the controllers and sensors.
> Make sure all hardware connections (fans, pumps, sensors) are wired and configured correctly.

---

## Developer Workflow (Raspberry Pi → GitHub)

Since Node-RED stores its data under `~/.node-red`, and this repository keeps a copy under `node-red/`, you can periodically sync them and push to GitHub:

```bash
# Sync Node-RED config into the repo (exclude credentials)
hn=$(hostname)
rsync -av --exclude "flows_${hn}_cred.json" ~/.node-red/ ~/Work/cja-skyfarms-project/node-red/

cd ~/Work/cja-skyfarms-project
git add .
git commit -m "Update Node-RED flows"
git push
```

This keeps your Node-RED flows and settings backed up and version-controlled, while avoiding sensitive credential files.

---

## Key Features

* Control of environmental devices such as:

  * DC fans
  * Air circulators
  * LED and UV-C modules
  * Nutrient solution pumps
  * Concentration of Nutrient solution with peristaltic pumps
* Real-time sensor data monitoring:

  * EC and pH
  * Temperature and humidity
  * Nutrient solution input history
* Node-RED–based GUI for intuitive operation
* Modular and extensible architecture for adding new devices
* Optional camera streaming for visual monitoring of the plant factory

---

## Contributing and Contact

* Please submit issues and pull requests via the GitHub repository.
* For questions or collaboration related to CJA SKYFARMS or this project, feel free to open an issue and describe your use case.

```

---

혹시 이 README에 **한국어 섹션(예: “개발자용 요약” 같은 것)**도 추가하고 싶으면, 같은 구조로 한글 버전도 붙여서 `README_ko.md` 따로 만들거나 아래에 한 섹션 더 달아주는 것도 괜찮아.  
원하면 한국어 버전도 같이 만들어줄게!
```
