#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"

if [ -f "${SCRIPT_DIR}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "${SCRIPT_DIR}/.env"
  set +a
fi

PYTHON_BIN="${BUTTERHEAD_PYTHON:-${VENV_DIR}/bin/python}"
LOG_FILE="${BUTTERHEAD_JOB_LOG:-${LOG_DIR}/daily_capture_job.log}"

ARGS=(
  "${SCRIPT_DIR}/capture_daily_and_predict.py"
  "--plant-id" "${BUTTERHEAD_PLANT_ID:-butterhead-01}"
  "--batch-id" "${BUTTERHEAD_BATCH_ID:-default-batch}"
)

if [ -n "${BUTTERHEAD_PLANTING_DATE:-}" ]; then
  ARGS+=("--planting-date" "${BUTTERHEAD_PLANTING_DATE}")
fi

if [ -n "${BUTTERHEAD_MODEL_PATH:-}" ]; then
  ARGS+=("--model" "${BUTTERHEAD_MODEL_PATH}")
fi

if [ -n "${BUTTERHEAD_CAMERA_DEVICE:-}" ]; then
  ARGS+=("--device" "${BUTTERHEAD_CAMERA_DEVICE}")
fi

if [ -n "${BUTTERHEAD_CAPTURE_WIDTH:-}" ]; then
  ARGS+=("--width" "${BUTTERHEAD_CAPTURE_WIDTH}")
fi

if [ -n "${BUTTERHEAD_CAPTURE_HEIGHT:-}" ]; then
  ARGS+=("--height" "${BUTTERHEAD_CAPTURE_HEIGHT}")
fi

exec "${PYTHON_BIN}" "${ARGS[@]}" >>"${LOG_FILE}" 2>&1
