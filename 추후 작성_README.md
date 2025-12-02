# CJA SKYFARMS Smart Farm Control Project

## Overview

This project is a system that controls the smart farm environment of CJA SKYFARMS using Python.
It integrates and manages various environmental control devices and sensors, such as fans, air circulators, and nutrient pumps,
and allows easy control through a Tkinter-based GUI.

## Folder Structure

```
cja-skyfarms-project/
├── main.py                         # Main execution file (UI and overall control)
├── controllers/                    # Environmental control modules
│   ├── FanController.py            # DC fan control code
│   ├── AirCirculatorController.py  # Air circulator control code
│   ├── LEDController.py            # LED control code
│   ├── UVController.py             # UV-C control code
│   └── PumpController.py           # Nutrient pump control code
├── sensors/                        # Sensor data collection modules
│   ├── EC_pH.py                    # EC, pH sensor data collecting code
│   ├── Temp_humi.py                # Temperature and humidity sensor data collecting code
│   ├── EC_pH_log.csv               # EC, pH sensor data
│   ├── Temp_humi_log.csv           # Temperature and humidity sensor data
│   └── Solution_input_log.csv      # A,B and Acid solution input data
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
   # Video4Linux 유틸리티 설치
   sudo apt update
   sudo apt install v4l-utils

   # 연결된 카메라 목록 확인
   v4l2-ctl --list-devices

   # 지원하는 해상도와 포맷 확인
   v4l2-ctl --list-formats-ext -d /dev/video0

   # 카메라의 모든 설정 정보 확인
   v4l2-ctl --all -d /dev/video0
   # fswebcam 설치
   sudo apt install fswebcam

   # 기본 해상도로 사진 촬영
   fswebcam -d /dev/video0 -r 640x480 test.jpg

   **mjpg-streamer 설치**
   # 필요한 개발 도구 설치
   sudo apt install cmake libjpeg8-dev gcc g++ git

   # mjpg-streamer 소스 다운로드
   cd ~
   git clone https://github.com/jacksonliam/mjpg-streamer.git
   cd mjpg-streamer/mjpg-streamer-experimental

   # 컴파일 및 설치
   make
   sudo make install
   # 기본 스트리밍 (포트 8080)
   ./mjpg_streamer \
   -i "input_uvc.so -d /dev/video0 -r 640x480 -f 30" \
   -o "output_http.so -p 8080 -w www"

   # HD 스트리밍 (고품질)
   ./mjpg_streamer \
   -i "input_uvc.so -d /dev/video0 -r 1280x720 -f 15" \
   -o "output_http.so -p 8080 -w www"
   ```

2. **Run the program**

   ```
   node-red-start

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
