# Butterhead Weight Estimation

This directory contains a camera-first workflow for daily butterhead lettuce image capture,
EXIF metadata storage, weight prediction, automatic feature-model retraining, ONNX inference,
and daily automation.
The current capture path is OpenCV-only: direct V4L2 capture from the webcam, with a USB reset
retry if the camera fails to respond.

Each captured image now stores extra plant descriptors in EXIF metadata:
`plant_height_cm`, `plant_width_cm`, `leaf_color`, `leaf_color_score`,
plus ratio fields and Korean aliases `초장`, `초폭`, `엽색`.

## Why this model

- `EfficientNet-B0` keeps the backbone small enough for Raspberry Pi CPU inference while
  still using a modern pretrained vision model.
- The regressor also consumes handcrafted canopy features:
  `green_area_ratio`, `canopy_bbox_ratio`, `excess_green_mean`, `days_since_planting`,
  `plant_height_cm`, `plant_width_cm`, `leaf_color_score`.
- This hybrid approach is usually more data-efficient than pure image-only regression when
  the farm dataset is still small.
- When no trained model exists yet, the system now falls back to a lightweight bootstrap
  feature regressor built from `plant_height_cm`, `plant_width_cm`, `leaf_color_score`,
  canopy area, and days since planting.
- Once manual weight labels accumulate in `camera/data/labels/butterhead_weights.csv`,
  the monitor automatically retrains the lightweight feature regressor and starts using it.

## Files

- `capture_daily_and_predict.py`: capture one image, write EXIF metadata, run inference, log the result
- `monitor_butterhead.py`: stay running and capture/analyze once per day automatically
- `train_butterhead_feature_regressor.py`: manually retrain the lightweight feature regressor
- `train_butterhead_regressor.py`: train the weight regressor and export ONNX
- `predict_butterhead_weight.py`: run inference for an existing image
- `record_butterhead_weight_label.py`: append a real measured weight label and optionally retrain
- `install_daily_capture_cron.py`: install a daily cron job
- `run_daily_butterhead_job.sh`: shell wrapper for cron
- `run_butterhead_monitor.sh`: shell wrapper for the long-running monitor

## Training label CSV

Create `camera/data/labels/butterhead_weights.csv` with at least:

```csv
image_path,weight_g,planting_date,split
/home/cja/Work/cja-skyfarms-project/camera/data/captures/2026/03/butterhead-01__20260309_090000.jpg,132.5,2026-03-01,train
```

`split` is optional. If it is missing, the trainer creates a random validation split.

The long-running monitor watches this file automatically.

- Before enough labels exist, the monitor uses `camera/data/models/butterhead_weight_bootstrap.json`
- After at least `BUTTERHEAD_AUTO_TRAIN_MIN_LABELS` rows exist, it trains
  `camera/data/models/butterhead_weight_feature_regressor.json`
- It retrains again whenever at least `BUTTERHEAD_AUTO_TRAIN_MIN_NEW_LABELS` new labeled rows are added

## Setup

```bash
cd /home/cja/Work/cja-skyfarms-project/camera
./setup_camera_env.sh
cp .env.example .env
```

## Daily capture

```bash
cd /home/cja/Work/cja-skyfarms-project/camera
./.venv/bin/python capture_daily_and_predict.py --plant-id butterhead-01 --planting-date 2026-03-01
```

If no explicit model is provided, this command automatically chooses:

1. `butterhead_weight_feature_regressor.json` if auto-trained
2. `butterhead_weight_efficientnet_b0.onnx` if it exists
3. `butterhead_weight_bootstrap.json` otherwise

## Continuous monitor

The current defaults assume:

- camera model: Logitech C270
- distance to tray: 26 cm
- field of view: 55 degrees, interpreted as diagonal FOV
- capture schedule: once per day at `BUTTERHEAD_MONITOR_HOUR:BUTTERHEAD_MONITOR_MINUTE`
- capture backend: OpenCV direct capture only

Run once and keep the process alive:

```bash
cd /home/cja/Work/cja-skyfarms-project/camera
./run_butterhead_monitor.sh
```

The first run happens immediately. After that, the process waits until the next daily schedule.
Each run captures a photo, writes EXIF, predicts weight, and logs results to CSV and
`/home/cja/Work/cja-skyfarms-project/data/data.db`.
Captured photos and previews are now grouped by `year/month` rather than `year/month/day`.
If another process is holding `/dev/video0`, OpenCV capture can fail, so do not run
`mjpg_streamer` in parallel with this monitor.

## Bootstrap and Auto Training

Bootstrap model creation is automatic, but you can also force a retrain from labeled data:

```bash
cd /home/cja/Work/cja-skyfarms-project/camera
./.venv/bin/python train_butterhead_feature_regressor.py --force
```

Useful environment variables:

- `BUTTERHEAD_AUTO_TRAIN_ENABLED=1`
- `BUTTERHEAD_AUTO_TRAIN_MIN_LABELS=10`
- `BUTTERHEAD_AUTO_TRAIN_MIN_NEW_LABELS=3`

To add a real measured weight label:

```bash
cd /home/cja/Work/cja-skyfarms-project/camera
./.venv/bin/python record_butterhead_weight_label.py \
  --image /home/cja/Work/cja-skyfarms-project/camera/data/captures/2026/03/butterhead-01__20260309_090000.jpg \
  --weight-g 132.5 \
  --planting-date 2026-03-01
```

## Install daily cron

```bash
cd /home/cja/Work/cja-skyfarms-project/camera
./.venv/bin/python install_daily_capture_cron.py --hour 9 --minute 0
```
