# CJA SKYFARMS 스마트팜 시스템

Raspberry Pi 기반 수경재배 식물공장 자동화 시스템.
환경 센서 모니터링, 양액 자동 제어, AI 카메라 생육 추정을 통합 관리한다.

## 시스템 구성도

```
┌─────────────── 하드웨어 ───────────────┐
│  센서              제어기          카메라  │
│  EC/pH (RS485)     LED/UV (GPIO)  C270   │
│  온습도/CO2        팬/펌프 (GPIO)  USB    │
└──────────┬────────────┬────────────┬─────┘
           ▼            ▼            ▼
┌─────── Python 센서/컨트롤러 레이어 ───────┐
│  sensors/          controllers/    camera/ │
│  EC·pH 읽기        GPIO 릴레이     캡처    │
│  온습도·CO2 읽기   자동 양액 투입  AI 추정 │
└──────────┬────────────┬────────────┬─────┘
           ▼            ▼            ▼
┌──────── Node-RED 오케스트레이션 ──────────┐
│  pythonshell 노드 → GPIO 출력            │
│  대시보드 UI (스위치, 게이지, 차트)       │
│  스케줄 관리, 수동 투입 UI               │
└──────────────────┬───────────────────────┘
                   ▼
┌─────────── SQLite (data.db) ─────────────┐
│  EC/pH 로그, 온습도 로그, 양액 투입 이력  │
│  카메라 생육 기록 (무게/초장/초폭/엽색)   │
└──────────────────┬───────────────────────┘
                   ▼
    웹 대시보드 (Node-RED :1880)
    카메라 스트리밍 (mjpg-streamer :8080)
```

## 디렉토리 구조

```
cja-skyfarms-project/
├── camera/                           # 생육 모니터링 (AI 카메라)
│   ├── butterhead_weight/            #   코어 패키지 (19개 모듈)
│   ├── data/                         #   캡처 이미지, 모델, 라벨
│   ├── logs/                         #   모니터 로그, 예측 CSV
│   ├── .env                          #   카메라 설정
│   ├── run_butterhead_monitor.sh     #   모니터 실행 래퍼
│   ├── start_mjpg_streamer_safe.sh   #   스트리머 실행 래퍼
│   └── README.md                     #   카메라 시스템 상세 문서
│
├── controllers/                      # 디바이스 제어 (GPIO 릴레이)
│   ├── Dist_1_EC_pH_auto_control.py  #   1구역 EC/pH 자동 제어
│   ├── Dist_2_EC_pH_auto_control.py  #   2구역 EC/pH 자동 제어
│   ├── Dist_1_LEDController.py       #   1구역 LED (04:00~22:00)
│   ├── Dist_2_LEDController.py       #   2구역 LED (05:00~21:00)
│   ├── Dist_1_UVController.py        #   1구역 UV-C
│   ├── Dist_2_UVController.py        #   2구역 UV-C
│   ├── Dist_1_PumpController.py      #   1구역 양액 펌프
│   ├── Dist_2_PumpController.py      #   2구역 양액 펌프
│   ├── Dist_2_FanController.py       #   2구역 팬 (05:00~22:00)
│   └── AirCirculatorController.py    #   공용 공기순환기
│
├── sensors/                          # 센서 데이터 수집
│   ├── Dist_1_EC_pH.py               #   1구역 EC/pH (RS485 Modbus)
│   ├── Dist_2_EC_pH.py               #   2구역 EC/pH (RS485 Modbus)
│   └── room_condition.py             #   온도/습도/CO2
│
├── data/                             # 데이터 저장
│   ├── data.db                       #   SQLite DB (전체 로그)
│   ├── csv_to_sqlite.py              #   CSV → DB 임포트 유틸
│   └── import_solution_logs_to_sqlite.py
│
├── node-red/                         # Node-RED 플로우 스냅샷
│   ├── flows.json                    #   플로우 정의
│   ├── package.json                  #   npm 의존성
│   └── README.md
│
├── main.py                           # Tkinter 로컬 UI (선택)
├── requirements.txt                  # Python 의존성
└── README.md                         # 이 문서
```

## 하드웨어

### 센서

| 센서 | 프로토콜 | 포트 | 수집 주기 |
|------|---------|------|----------|
| EC/pH (1구역, 2구역) | RS485 Modbus RTU (9600bps) | `/dev/serial/by-path/...` | 20분 |
| 온도/습도/CO2 | RS485 시리얼 (38400bps) | `/dev/serial/by-id/usb-1a86...` | 20분 |
| 카메라 (Logitech C270) | USB V4L2 | `/dev/video0` | 06:00, 18:00 |

### 제어기 (GPIO, Active-Low 릴레이)

| 장치 | GPIO | 구역 | 동작 |
|------|------|------|------|
| LED | GPIO4 / GPIO14 | Dist 1 / 2 | 스케줄 (04~22시 / 05~21시) |
| UV-C | GPIO18 / GPIO25 | Dist 1 / 2 | 수동 또는 스케줄 |
| A/B 펌프 | GPIO17 | Dist 1 / 2 | EC < 1.1 dS/m 시 자동 투입 |
| 산 펌프 | GPIO21 | Dist 1 / 2 | pH > 5.9 시 자동 투입 |
| 팬 | GPIO20 | Dist 2 | 스케줄 (05~22시) |
| 공기순환기 | GPIO16 | 공용 | 스케줄 |

펌프 캘리브레이션: 1.65 mL/sec, 1회 투입량: 5.0 mL

### 양액 자동 제어 로직

4시간 간격 (00/04/08/12/16/20시)으로 센서를 읽고:
- EC < 1.1 dS/m → A/B 펌프 5mL 투입
- pH > 5.9 → 산 펌프 5mL 투입
- 투입 이력은 `Dist_X_Solution_input_log` 테이블에 기록

## 카메라 생육 모니터링

USB 웹캠으로 버터헤드 상추를 자동 촬영하고, 무게/초장/초폭을 AI로 추정한다.

### 생육 주기별 동작

| 단계 | 조건 | 동작 |
|------|------|------|
| **발아/육묘** | 정식 전 (green < 3%) | 사진만 저장, 정식 자동 감지 대기 |
| **정식 후** (프레임 내) | green < 95% | 이미지에서 직접 측정 (HSV 마스크 → cm 환산) |
| **프레임 오버플로** | green >= 95% | 로지스틱 성장 곡선으로 추정 |

- 정식 감지: green_area_ratio >= 0.03이 **2회 연속** → 자동 전환
- 성장 곡선: `y(t) = y_max / (1 + e^(-k·(t - t_mid)))` (문헌 기반 + 실측 캘리브레이션)

상세 사용법은 [`camera/README.md`](camera/README.md) 참조.

## 데이터베이스

**경로**: `data/data.db` (SQLite, WAL 모드)

### 테이블

| 테이블 | 내용 | 주요 컬럼 |
|--------|------|----------|
| `Dist_1_EC_pH_log` | 1구역 양액 센서 | Date, EC, pH, Solution_Temperature |
| `Dist_2_EC_pH_log` | 2구역 양액 센서 | Date, EC, pH, Solution_Temperature |
| `Temp_humi_log` | 환경 센서 | Date, Temperature, Humidity, CO2 |
| `Dist_1_Solution_input_log` | 1구역 투입 이력 | Date, device, action, detail (mL) |
| `Dist_2_Solution_input_log` | 2구역 투입 이력 | Date, device, action, detail (mL) |
| `camera_butterhead_weight_log` | 캡처별 생육 상세 | Date, PlantId, PredictedWeightG, PlantHeightCm, PlantWidthCm, GreenAreaRatio, LeafColor |
| `camera_butterhead_growth_log` | 생육 일별 요약 | Date, PlantId, PredictedWeightG, PlantHeightCm, PlantWidthCm |

## 서비스 관리

### systemd 유저 서비스

```bash
# 생육 모니터 (상시 실행, 06:00/18:00 촬영)
systemctl --user start butterhead-monitor
systemctl --user stop butterhead-monitor
systemctl --user restart butterhead-monitor
systemctl --user status butterhead-monitor

# 카메라 스트리밍 (HTTP :8080)
systemctl --user start mjpg-streamer
systemctl --user stop mjpg-streamer
```

부팅 시 자동 실행 설정됨 (`enable` + `loginctl enable-linger`).

### Node-RED

```bash
sudo systemctl start nodered      # 시작
sudo systemctl stop nodered       # 중지
```

대시보드: `http://<hostname>:1880/`

### 로그 확인

```bash
# 생육 모니터 실시간 로그
journalctl --user -u butterhead-monitor -f

# 또는 직접
tail -f camera/logs/butterhead_monitor.log

# DB 직접 조회
sqlite3 data/data.db "SELECT Date, EC, pH FROM Dist_1_EC_pH_log ORDER BY Date DESC LIMIT 5;"
```

## 설치

### 1. Python 환경

```bash
cd ~/Work/cja-skyfarms-project
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install minimalmodbus
```

카메라 시스템은 별도 venv 사용:
```bash
cd camera
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Node-RED

```bash
bash <(curl -sL https://raw.githubusercontent.com/node-red/linux-installers/master/deb/update-nodejs-and-nodered)
sudo systemctl enable nodered.service
sudo systemctl start nodered.service
```

필요한 노드:
```bash
cd ~/.node-red
npm install node-red-contrib-pythonshell node-red-dashboard node-red-node-pi-gpio
```

### 3. mjpg-streamer

```bash
sudo apt install cmake libjpeg8-dev gcc g++
cd ~
git clone https://github.com/jacksonliam/mjpg-streamer.git
cd mjpg-streamer/mjpg-streamer-experimental
make && sudo make install
```

### 4. 시스템 도구

```bash
sudo apt install v4l-utils jq sqlite3
```

## 새 배치 시작 (카메라)

```bash
# 1. camera/.env 수정
vi camera/.env
```
```bash
BUTTERHEAD_PLANT_ID=butterhead-02       # 새 식물 ID
BUTTERHEAD_BATCH_ID=batch-2026-04       # 새 배치 ID
BUTTERHEAD_PLANTING_DATE=               # 비우면 카메라가 정식 자동 감지
```
```bash
# 2. 모니터 재시작
systemctl --user restart butterhead-monitor
```

이전 배치 데이터는 DB에 PlantId/BatchId로 구분되어 보존된다.

## 성장 곡선 캘리브레이션

실측값을 넣으면 프레임 오버플로 이후 추정이 정확해진다:

```bash
cd camera
.venv/bin/python -c "
from butterhead_weight.growth_model import build_growth_model
from butterhead_weight.config import load_runtime_config
config = load_runtime_config()
build_growth_model(config, 'butterhead-01', 'default-batch',
    manual_calibrations=[
        {'days': 33, 'weight_g': 162.0, 'height_cm': 15.0, 'width_cm': 21.0},
    ])
print('Saved.')
"
```

## Node-RED 플로우 동기화

```bash
hn=$(hostname)
rsync -av --exclude "flows_${hn}_cred.json" ~/.node-red/ ~/Work/cja-skyfarms-project/node-red/
cd ~/Work/cja-skyfarms-project
git add node-red/
git commit -m "Update Node-RED flows"
```

## 기술 스택

| 분류 | 기술 |
|------|------|
| 하드웨어 | Raspberry Pi, Logitech C270, RS485 Modbus 센서, GPIO 릴레이 |
| 백엔드 | Python 3.11, Node-RED |
| AI/ML | OpenCV, ONNX Runtime, EfficientNet-B0, 로지스틱 성장 곡선 |
| 데이터 | SQLite (WAL), CSV |
| 통신 | RS485 Modbus RTU, USB V4L2, GPIO |
| 서비스 | systemd (user), Node-RED |
| 웹 | Node-RED Dashboard (:1880), mjpg-streamer (:8080) |
