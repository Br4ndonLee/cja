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
├── main.py                           # Tkinter-based local UI (optional)
├── controllers/                      # Actuator & automation scripts
│   ├── AirCirculatorController.py
│   ├── Dist_1_EC_pH_auto_control.py  # Dist 1 auto EC/pH control + pump dosing
│   ├── Dist_2_EC_pH_auto_control.py  # Dist 2 auto EC/pH control + pump dosing
│   ├── Dist_1_LEDController.py
│   ├── Dist_2_LEDController.py
│   ├── Dist_1_UVController.py
│   ├── Dist_2_UVController.py
│   ├── Dist_1_PumpController.py
│   ├── Dist_2_PumpController.py
│   └── Dist_2_FanController.py
├── sensors/                          # Sensor data collection
│   ├── Dist_1_EC_pH.py
│   ├── Dist_2_EC_pH.py
│   └── room_condition.py
├── data/                             # Data storage & utilities
│   ├── data.db                       # SQLite DB (solution inputs, EC/pH, room logs)
│   ├── data.db-wal                   # SQLite WAL (runtime)
│   ├── data.db-shm                   # SQLite shared memory (runtime)
│   ├── csv_to_sqlite.py              # CSV -> SQLite import utility
│   ├── import_solution_logs_to_sqlite.py
│   ├── Dist_1_pump_activate_result.csv
│   └── Dist_2_pump_activate_result.csv
├── node-red/                         # Node-RED local snapshot (mirrors runtime project)
│   ├── flows.json                    # Flow snapshot
│   ├── flows_cred.json               # Flow credentials (do not commit)
│   ├── package.json                  # Node-RED dependencies
│   ├── README.md
│   └── ui-media/
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

## Logging & Database (SQLite)

The system now uses a single SQLite database for solution input logs and other sensor logs.

**DB path**

- `/home/cja/Work/cja-skyfarms-project/data/data.db`

**Tables used for solution input**

- `Dist_1_Solution_input_log` (Date TEXT, device TEXT, action TEXT, detail REAL)
- `Dist_2_Solution_input_log` (Date TEXT, device TEXT, action TEXT, detail REAL)

**Write sources**

- Manual solution inputs from Node-RED write directly to SQLite.
- Auto-control pump actions (via Python controllers) also write to the same tables.

**Important**

- The Node-RED sqlite nodes run SQL from `msg.topic`.
- Manual dosing function nodes build full SQL strings (no placeholders) and send them via `msg.topic`.

---

## Node-RED Project Notes

Primary flow file (runtime):

- `~/.node-red/projects/cja-skyfarms/flows.json`

Repo mirror (for reference/backups):

- `node-red/projects/cja-skyfarms/flows.json`

After editing flows.json directly:

1. Restart Node-RED or re-import the flow in the editor.
2. Deploy.

---

## How It Works (Runtime Flow)

1. **Node-RED UI** provides:
   - Auto mode toggles (Dist 1 / Dist 2).
   - Manual dosing inputs (A/B, Acid).
2. **Python controllers** run via Node-RED `pythonshell` nodes:
   - Read sensors, apply filtering, and decide dosing.
   - Emit GPIO commands and dosing logs back to Node-RED as JSON.
3. **GPIO output nodes** control hardware relays.
4. **SQLite logging** stores all solution input actions in:
   - `Dist_1_Solution_input_log`
   - `Dist_2_Solution_input_log`

---

## Controllers (Summary)

**Dist 1**

- `controllers/Dist_1_EC_pH_auto_control.py`  
  Auto EC/pH control loop for Dist 1. Reads sensor values, decides dosing, triggers pumps via Node-RED GPIO, and logs solution input to SQLite.
- `controllers/Dist_1_PumpController.py`  
  Manual/triggered pump control logic for Dist 1 (A/B and Acid).
- `controllers/Dist_1_LEDController.py`  
  LED control for Dist 1 (schedule/on-off).
- `controllers/Dist_1_UVController.py`  
  UV control for Dist 1.

**Dist 2**

- `controllers/Dist_2_EC_pH_auto_control.py`  
  Auto EC/pH control loop for Dist 2. Reads sensor values, decides dosing, triggers pumps via Node-RED GPIO, and logs solution input to SQLite.
- `controllers/Dist_2_PumpController.py`  
  Manual/triggered pump control logic for Dist 2 (A/B and Acid).
- `controllers/Dist_2_LEDController.py`  
  LED control for Dist 2 (schedule/on-off).
- `controllers/Dist_2_UVController.py`  
  UV control for Dist 2.
- `controllers/Dist_2_FanController.py`  
  Fan control for Dist 2.

**Shared**

- `controllers/AirCirculatorController.py`  
  Air circulation control.

---

## Node-RED Flow (Summary)

**Auto control (Dist 1 / Dist 2)**

- `ui_switch` toggles Auto mode.
- `pythonshell in` runs `Dist_1_EC_pH_auto_control.py` or `Dist_2_EC_pH_auto_control.py`.
- `split lines → json` parses Python JSON output.
- `Dispatch GPIO by topic` routes:
  - GPIO commands to `rpi-gpio out`.
  - dosing logs to SQLite (solution input tables).

**Manual dosing (Dist 1 / Dist 2)**

- UI inputs set dosing volume (ml) and compute duration.
- Manual run buttons trigger a function node:
  - Turn GPIO ON → wait duration → OFF.
  - Build SQL and write to SQLite.

**SQLite**

- Solution input logs are inserted into:
  - `Dist_1_Solution_input_log`
  - `Dist_2_Solution_input_log`
- SQL is passed via `msg.topic` (no placeholders).

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
