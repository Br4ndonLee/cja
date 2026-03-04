#!/usr/bin/env bash
set -u

LOG_FILE="/tmp/mjpg.log"
DEVICE="/dev/v4l/by-id/usb-046d_C270_HD_WEBCAM_200901010001-video-index0"
RESOLUTION="${MJPG_RESOLUTION:-1280x720}"
FPS="${MJPG_FPS:-5}"
PORT="${MJPG_PORT:-8080}"

BIN="/usr/local/bin/mjpg_streamer"
INPUT_SO="/usr/local/lib/mjpg-streamer/input_uvc.so"
OUTPUT_SO="/usr/local/lib/mjpg-streamer/output_http.so"
WWW_DIR="/usr/local/share/mjpg-streamer/www"

if [ ! -x "$BIN" ]; then
  BIN="/home/cja/mjpg-streamer/mjpg-streamer-experimental/mjpg_streamer"
  INPUT_SO="/home/cja/mjpg-streamer/mjpg-streamer-experimental/input_uvc.so"
  OUTPUT_SO="/home/cja/mjpg-streamer/mjpg-streamer-experimental/output_http.so"
  WWW_DIR="/home/cja/mjpg-streamer/mjpg-streamer-experimental/www"
fi

if pgrep -x mjpg_streamer >/dev/null 2>&1; then
  exit 0
fi

if [ ! -e "$DEVICE" ]; then
  echo "$(date '+%F %T') camera device missing: $DEVICE" >> "$LOG_FILE"
  exit 1
fi

for try in 1 2 3; do
  if pgrep -x mjpg_streamer >/dev/null 2>&1; then
    exit 0
  fi

  echo "$(date '+%F %T') start attempt ${try}" >> "$LOG_FILE"
  "$BIN" -b \
    -i "${INPUT_SO} -d ${DEVICE} -r ${RESOLUTION} -f ${FPS} -n" \
    -o "${OUTPUT_SO} -p ${PORT} -w ${WWW_DIR}" >> "$LOG_FILE" 2>&1 || true

  sleep 2
done

if pgrep -x mjpg_streamer >/dev/null 2>&1; then
  exit 0
fi

echo "$(date '+%F %T') failed to start mjpg_streamer after retries" >> "$LOG_FILE"
exit 1
