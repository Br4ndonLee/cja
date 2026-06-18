# Butterhead 생육 모니터링 시스템

Logitech C270 웹캠으로 버터헤드 상추를 자동 촬영하고, 무게/초장/초폭을 추정하는 시스템.
Raspberry Pi에서 상시 동작하며, 발아부터 수확까지 전체 생육 주기를 기록한다.

## 시스템 구조

```
카메라 캡처 (06:00/18:00)
    │
    ├── 정식 전: 사진 + 날짜만 기록, 녹색 감지로 정식 자동 인식
    │
    └── 정식 후: 사진 + 피처 추출 + 무게/초장/초폭 추정
                    │
                    ├── 프레임 내 식물 → 이미지에서 직접 측정
                    └── 프레임 오버플로 → 로지스틱 성장 곡선으로 추정
```

## 빠른 시작

### 1. 초기 설정

```bash
cd /home/cja/Work/cja-skyfarms-project/camera
./setup_camera_env.sh
cp .env.example .env
```

### 2. `.env` 설정

```bash
BUTTERHEAD_PLANT_ID=butterhead-01          # 식물 ID
BUTTERHEAD_BATCH_ID=batch-2026-04          # 배치 ID
BUTTERHEAD_PLANTING_DATE=                  # 비워두면 카메라가 정식 자동 감지
BUTTERHEAD_CAMERA_DEVICE=/dev/v4l/by-id/usb-046d_C270_HD_WEBCAM_200901010001-video-index0
BUTTERHEAD_CAMERA_DISTANCE_CM=26.0         # 카메라~트레이 거리 (cm)
BUTTERHEAD_CAMERA_FOV_DEG=60.0             # Logitech C270 대각 FOV
BUTTERHEAD_MONITOR_TIMES=06:00,18:00       # 촬영 시각 (24h, 쉼표 구분)
```

### 3. 서비스 시작

```bash
# 시작
systemctl --user start butterhead-monitor

# 상태 확인
systemctl --user status butterhead-monitor
```

부팅 시 자동 실행이 이미 설정되어 있다 (`enable` + `linger`).

## 서비스 관리

```bash
# 시작 / 중지 / 재시작
systemctl --user start butterhead-monitor
systemctl --user stop butterhead-monitor
systemctl --user restart butterhead-monitor    # 코드 수정 후 반드시 재시작

# 실시간 로그
journalctl --user -u butterhead-monitor -f

# 또는 로그 파일 직접 확인
tail -f logs/butterhead_monitor.log

# mjpg-streamer (웹 스트리밍, 포트 8080)
systemctl --user start mjpg-streamer
systemctl --user stop mjpg-streamer
```

| 서비스 | 설명 | 타입 |
|--------|------|------|
| `butterhead-monitor` | 생육 모니터링 (06:00/18:00 캡처 + 추정) | 상주 프로세스 |
| `mjpg-streamer` | 카메라 HTTP 스트리밍 (8080) | 백그라운드 |

## 생육 주기별 동작

### Phase 1: 발아/육묘 (정식 전)

`.env`에서 `BUTTERHEAD_PLANTING_DATE`를 비워두면 자동 감지 모드로 동작한다.

- 매 촬영마다 사진 저장 + 날짜 기록
- HSV 녹색 마스크로 green_area_ratio 계산
- **2회 연속** green_area_ratio >= 0.03 이면 → 정식 확인, 첫 감지일 = 정식일(Day 0)
- DB에 `estimation_method = "pre_transplant"` 으로 기록

```
04/03 06:00  green=0.005  빈 트레이     → waiting (사진만)
04/05 06:00  green=0.065  묘종 놓임!    → candidate (1차 감지)
04/05 18:00  green=0.072  여전히 있음   → confirmed! 정식일=04/05
04/06 06:00  green=0.095  성장 시작     → 전체 분석 시작
```

수동으로 정식일을 지정하려면:
```bash
BUTTERHEAD_PLANTING_DATE=2026-04-15     # 과거 날짜 = 즉시 분석 모드
```

### Phase 2: 정식 후 (카메라 범위 내)

- 이미지에서 HSV 녹색 마스크로 식물 영역 추출
- 초장/초폭: 마스크 바운딩박스 + 씬 크기(FOV) 기반 cm 환산
- 무게: feature regressor (또는 bootstrap 모델)로 예측
- 엽색: excess_green + saturation 기반 분류

### Phase 3: 프레임 오버플로 (카메라 범위 초과)

green_area_ratio >= 0.95 이면 식물이 프레임을 벗어난 것으로 판단한다.

- **로지스틱 성장 곡선**으로 초장/초폭/무게를 추정:
  ```
  y(t) = y_max / (1 + e^(-k·(t - t_mid)))
  ```
- Phase 2 기간의 측정값 + 수동 캘리브레이션으로 곡선 파라미터를 피팅
- DB에 `estimation_method = "growth_curve"` 로 기록

## 수동 캘리브레이션 (성장 곡선 보정)

실측값을 넣으면 성장 곡선 정확도가 올라간다.

```python
cd /home/cja/Work/cja-skyfarms-project/camera
.venv/bin/python -c "
from butterhead_weight.growth_model import build_growth_model
from butterhead_weight.config import load_runtime_config

config = load_runtime_config()
build_growth_model(
    config, 'butterhead-01', 'default-batch',
    manual_calibrations=[
        {'days': 33, 'weight_g': 162.0, 'height_cm': 15.0, 'width_cm': 21.0},
    ],
)
print('Calibration saved.')
"
```

실측값을 추가할수록 곡선이 더 정확해진다. 캘리브레이션 데이터는
`data/models/growth_calibration.json`에 저장된다.

## 무게 라벨 등록 (모델 학습용)

실제 무게를 측정했으면 기록해두면 자동 학습에 활용된다.

```bash
.venv/bin/python record_butterhead_weight_label.py \
  --image data/captures/2026/03/butterhead-01__20260309_090000.jpg \
  --weight-g 132.5 \
  --planting-date 2026-03-01
```

라벨 CSV: `data/labels/butterhead_weights.csv`
- 10개 이상 쌓이면 feature regressor 자동 학습
- 3개 추가될 때마다 자동 재학습

## 새 배치 시작

```bash
# 1. .env 수정
vi .env
```
```bash
BUTTERHEAD_PLANT_ID=butterhead-02
BUTTERHEAD_BATCH_ID=batch-2026-04
BUTTERHEAD_PLANTING_DATE=                  # 비우면 자동 감지
```
```bash
# 2. 모니터 재시작
systemctl --user restart butterhead-monitor
```

이전 배치 데이터는 DB에 PlantId/BatchId로 구분되어 보존된다.

## 데이터 저장 위치

| 항목 | 경로 |
|------|------|
| 캡처 이미지 | `data/captures/YYYY/MM/` |
| 프리뷰 (마스크 오버레이) | `data/previews/YYYY/MM/` |
| 예측 로그 CSV | `logs/butterhead_weight_predictions.csv` |
| 모니터 로그 | `logs/butterhead_monitor.log` |
| SQLite DB | `/home/cja/Work/cja-skyfarms-project/data/data.db` |
| 모델 파일 | `data/models/` |
| 성장 곡선 캘리브레이션 | `data/models/growth_calibration.json` |
| 정식 감지 상태 | `data/models/transplant_state.json` |
| 무게 라벨 | `data/labels/butterhead_weights.csv` |

## DB 스키마

`data.db` (SQLite, WAL 모드) 안에 7개 테이블이 있다.

### camera_butterhead_weight_log (캡처별 상세)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| Date | TEXT | ISO 8601 타임스탬프 |
| PlantId | TEXT | 식물 ID |
| BatchId | TEXT | 배치 ID |
| ImagePath | TEXT | 캡처 이미지 절대경로 |
| PredictedWeightG | REAL | 추정 무게 (g), 정식 전이면 NULL |
| GreenAreaRatio | REAL | 녹색 영역 비율 (0~1) |
| CanopyBBoxRatio | REAL | 캐노피 바운딩박스 비율 |
| ExcessGreenMean | REAL | 초과 녹색 평균값 |
| DaysSincePlanting | REAL | 정식 후 경과일 |
| PlantHeightCm | REAL | 초장 (cm) |
| PlantWidthCm | REAL | 초폭 (cm) |
| LeafColor | TEXT | 엽색 분류 |
| LeafColorScore | REAL | 엽색 점수 (0~1) |
| CameraDistanceCm | REAL | 카메라 거리 |
| CameraFovDeg | REAL | FOV (도) |
| ModelPath | TEXT | 사용된 모델 경로 |

### camera_butterhead_growth_log (일별 요약)

Date, PlantId, BatchId, ImagePath, PredictedWeightG, PlantHeightCm, PlantWidthCm,
LeafColor, LeafColorScore, CameraDistanceCm, CameraFovDeg, CameraFovAxis, CameraModel

### 양액/환경 테이블

| 테이블 | 내용 |
|--------|------|
| Dist_1_EC_pH_log | 1구역 EC/pH/양액온도 |
| Dist_2_EC_pH_log | 2구역 EC/pH/양액온도 |
| Dist_1_Solution_input_log | 1구역 양액 투입 이력 |
| Dist_2_Solution_input_log | 2구역 양액 투입 이력 |
| Temp_humi_log | 온도/습도/CO2 |

## 파일 구조

```
camera/
├── .env                              # 환경 설정
├── run_butterhead_monitor.sh         # 모니터 실행 래퍼
├── start_mjpg_streamer_safe.sh       # 스트리머 실행 래퍼
├── monitor_butterhead.py             # 모니터 진입점
├── capture_daily_and_predict.py      # 1회 캡처 + 예측
├── predict_butterhead_weight.py      # 단일 이미지 예측
├── record_butterhead_weight_label.py # 무게 라벨 등록
├── train_butterhead_regressor.py     # ONNX 모델 학습
├── train_butterhead_feature_regressor.py  # feature regressor 학습
├── recalculate_butterhead_history.py # 과거 데이터 재계산
├── install_daily_capture_cron.py     # cron 등록 (레거시)
│
├── butterhead_weight/                # 코어 패키지
│   ├── config.py                     # 환경변수 → RuntimeConfig
│   ├── capture.py                    # 카메라 캡처 (재시도/USB 리셋)
│   ├── features.py                   # HSV 마스크, 피처 추출
│   ├── predict.py                    # ONNX/JSON 모델 추론
│   ├── pipeline.py                   # 전체 파이프라인 (캡처→분석→기록)
│   ├── monitor.py                    # 스케줄 루프
│   ├── growth_model.py               # 로지스틱 성장 곡선 모델
│   ├── transplant_detector.py        # 정식 자동 감지
│   ├── feature_regressor.py          # bootstrap/ridge 회귀 모델
│   ├── stabilization.py              # 예측값 안정화
│   ├── calibration.py                # bootstrap 모델 캘리브레이션
│   ├── auto_train.py                 # 자동 재학습
│   ├── logging_utils.py              # CSV/DB 기록
│   ├── metadata.py                   # EXIF 메타데이터 읽기/쓰기
│   ├── preprocess.py                 # 이미지 전처리
│   ├── dataset.py                    # 학습 데이터셋
│   ├── model.py                      # EfficientNet-B0 모델 정의
│   ├── training.py                   # 학습 루프
│   ├── feature_training.py           # feature regressor 학습
│   └── labeling.py                   # 라벨 관리
│
├── data/
│   ├── captures/YYYY/MM/             # 원본 캡처 이미지
│   ├── previews/YYYY/MM/             # 마스크 오버레이 프리뷰
│   ├── models/                       # 모델 + 캘리브레이션 파일
│   └── labels/                       # 무게 라벨 CSV
│
└── logs/
    ├── butterhead_monitor.log        # 모니터 로그
    └── butterhead_weight_predictions.csv  # 예측 기록 CSV
```

## 카메라 사양

| 항목 | 값 |
|------|---|
| 모델 | Logitech C270 HD |
| 해상도 | 1280 x 720 |
| FOV | 60 (대각) |
| 카메라 거리 | 26 cm |
| 씬 크기 | 약 26cm x 15cm |
| FPS | 5 (캡처 시) |

카메라 거리 26cm에서 씬 크기가 약 26x15cm이므로, 초폭 20cm 이상의
식물은 프레임을 벗어난다. 이 경우 성장 곡선 모델이 자동으로 전환된다.

## 트러블슈팅

**카메라 캡처 실패**
- 자동 3단계 복구: 재시도 → mjpg_streamer 중지 후 재시도 → USB 리셋 후 재시도
- 모니터 프로세스는 실패해도 죽지 않고 다음 스케줄까지 대기

**서비스가 안 뜸**
```bash
journalctl --user -u butterhead-monitor --since "5 min ago"
```

**무게 추정이 부정확함**
- 성장 곡선 수동 캘리브레이션 추가 (위 "수동 캘리브레이션" 섹션 참조)
- 라벨 데이터 추가 → 자동 재학습으로 모델 개선

**green_area_ratio가 항상 1.0**
- 식물이 프레임을 완전히 채운 상태 (정상)
- 성장 곡선 모드로 자동 전환됨
