# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import datetime
import select

# ===============================
# Settings
# ===============================

# Read ONLY the latest row from this CSV (last valid line)
SENSOR_CSV = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_2_EC_pH_log.csv"

# Schedule mode
# TEST: run at every HH:00 and HH:30 (minute boundary)
# PROD: run at every 4 hours (00/04/08/12/16/20) at HH:00 only
SCHEDULE_MODE = "1hour"  # "30min" or "4hour"
# SCHEDULE_MODE = "30min"

# Thresholds
EC_MIN = 1.1
PH_MAX = 6.1

# Pump dosing volume and calibration (ml per second)
DOSE_ML = 50.0
PUMP_ML_PER_SEC = 1.65

# Node-RED GPIO topics (updated as requested)
TOPIC_AB = "GPIO22"     # AB pump relay topic
TOPIC_ACID = "GPIO23"   # Acid pump relay topic

# Active-low relay: 0=ON, 1=OFF
GPIO_ON = 0
GPIO_OFF = 1

# Polling interval
POLL_SEC = 0.2

# ===============================
# Node-RED switch (stdin) handling
# ===============================
def read_payload():
    """
    Non-blocking stdin read for Node-RED pythonshell input.
    Expected values:
      - "false" -> keep running (Auto ON)
      - "true"  -> stop immediately (Auto OFF)
    Returns:
      True / False / None (if no new input)
    """
    if select.select([sys.stdin], [], [], 0)[0]:
        raw = sys.stdin.readline().strip().lower()
        if raw == "true":
            return False   # Auto OFF -> stop
        if raw == "false":
            return True    # Auto ON  -> run
    return None

def emit(obj):
    """Print one-line JSON for Node-RED (no extra prints)."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)

def gpio(topic: str, value: int):
    """Emit GPIO command JSON for Node-RED."""
    emit({"type": "gpio", "topic": topic, "payload": int(value)})

def force_all_off():
    """Safety: force both relays OFF via Node-RED."""
    gpio(TOPIC_AB, GPIO_OFF)
    gpio(TOPIC_ACID, GPIO_OFF)

# ===============================
# Time / schedule helpers
# ===============================
def now_str(sec=True) -> str:
    """Return current timestamp string."""
    fmt = "%Y-%m-%d %H:%M:%S" if sec else "%Y-%m-%d %H:%M"
    return datetime.datetime.now().strftime(fmt)

def fmt_num(x) -> str:
    """Format numbers: 2.0 -> '2', 2.5 -> '2.5'."""
    try:
        xf = float(x)
    except Exception:
        return str(x)
    if abs(xf - round(xf)) < 1e-9:
        return str(int(round(xf)))
    return f"{xf:g}"

def is_on_boundary(dt: datetime.datetime) -> bool:
    """
    Decide whether current time is on the schedule boundary.
    - 30min: minute is 0 or 30
    - 4hour: hour is multiple of 4 AND minute is 0
    """
    # if SCHEDULE_MODE == "30min":
    #     return (dt.minute % 30 == 0)
    # return (dt.hour % 4 == 0 and dt.minute in (0, 1))
    if SCHEDULE_MODE == "30min":
        return (dt.minute % 30 == 0)
    if SCHEDULE_MODE == "1hour":
        return (dt.minute == 0)          # every hour at HH:00
    # "4hour"
    return (dt.hour % 4 == 0 and dt.minute == 0)


def slot_stamp(dt: datetime.datetime) -> str:
    """
    Create a unique key for the current slot to prevent duplicate runs.
    - 30min: YYYYMMDDHH + (00 or 30)
    - 4hour: YYYYMMDD + HH (00/04/08/12/16/20)
    """
    dt0 = dt.replace(second=0, microsecond=0)

    if SCHEDULE_MODE == "30min":
        mm = 0 if dt0.minute < 30 else 30
        return dt0.strftime("%Y%m%d%H") + f"{mm:02d}"
    if SCHEDULE_MODE == "1hour":
        return dt0.strftime("%Y%m%d%H")
    hh = (dt0.hour // 4) * 4
    return dt0.strftime("%Y%m%d") + f"{hh:02d}"

# ===============================
# CSV reader (last line only)
# ===============================
def read_last_valid_row(csv_path: str):
    """
    Read the last non-empty line from CSV and parse:
      Date, EC, pH, Solution_Temperature
    Returns:
      (date_str, ec_float, ph_float, temp_float) or (None, None, None, None)
    """
    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        return None, None, None, None

    # Read tail bytes to avoid loading huge files
    try:
        with open(csv_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            tail = min(size, 8192)
            f.seek(-tail, os.SEEK_END)
            data = f.read().decode("utf-8", errors="replace")
    except Exception:
        return None, None, None, None

    lines = [ln.strip() for ln in data.splitlines() if ln.strip()]
    if not lines:
        return None, None, None, None

    for ln in reversed(lines):
        if ln.lower().startswith("date,") or ln.lower().startswith("date "):
            continue

        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 4:
            continue

        date_str = parts[0]
        try:
            ec = float(parts[1])
            ph = float(parts[2])
            temp = float(parts[3])
            return date_str, ec, ph, temp
        except Exception:
            continue

    return None, None, None, None

# ===============================
# Pump control via Node-RED GPIO
# ===============================
def wait_with_abort(seconds: float):
    """
    Wait for seconds while monitoring Auto OFF.
    Raises RuntimeError('auto_switch_off') if OFF arrives.
    """
    t0 = time.monotonic()
    while (time.monotonic() - t0) < max(0.0, seconds):
        sw = read_payload()
        if sw is False:  # Auto OFF
            raise RuntimeError("auto_switch_off")
        time.sleep(0.05)

def run_pump_via_nodered(topic: str, device_name: str, ml: float, sec_needed: float):
    """
    Run pump by emitting GPIO ON/OFF, and emit a log line object to Node-RED.
    """
    gpio(topic, GPIO_ON)
    try:
        wait_with_abort(sec_needed)
    finally:
        gpio(topic, GPIO_OFF)

    ts = now_str(sec=True)
    line = f"{ts},{device_name},volume,{fmt_num(ml)},duration,{fmt_num(round(sec_needed, 1))}s"
    emit({"type": "log", "device": device_name, "payload": line})

# ===============================
# One control cycle (CSV last row -> decide -> pump)
# ===============================
def control_once_from_csv():
    """
    One control cycle:
      1) Read latest row from SENSOR_CSV (last valid line only)
      2) If EC <= EC_MIN -> dose AB (GPIO22)
         If pH >= PH_MAX -> dose Acid (GPIO23)
    Returns: "OK" / "FAIL" / "STOP"
    """
    date_str, ec, ph, temp = read_last_valid_row(SENSOR_CSV)
    if ec is None or ph is None:
        emit({"type": "status", "status": "fail", "reason": "csv_read_failed"})
        return "FAIL"

    sec_needed = DOSE_ML / PUMP_ML_PER_SEC

    try:
        if ec <= EC_MIN:
            run_pump_via_nodered(TOPIC_AB, "AB", DOSE_ML, sec_needed)

        if ph >= PH_MAX:
            run_pump_via_nodered(TOPIC_ACID, "Acid", DOSE_ML, sec_needed)

        emit({
            "type": "status",
            "status": "ok",
            "csv_time": date_str,
            "ec": ec,
            "ph": ph,
            "temp": temp
        })
        return "OK"

    except RuntimeError as e:
        if str(e) == "auto_switch_off":
            force_all_off()
            emit({"type": "status", "status": "stopped", "reason": "switch_off_during_pump"})
            return "STOP"
        force_all_off()
        emit({"type": "status", "status": "fail", "reason": "runtime_error"})
        return "FAIL"

    except Exception:
        force_all_off()
        emit({"type": "status", "status": "fail", "reason": "unexpected_error"})
        return "FAIL"

# ===============================
# Main loop
# ===============================
def main_loop():
    """
    Controller-style stdin control:
      - Wait until we receive Auto ON ("false" => True) to start.
      - Run control_once_from_csv ONLY at schedule boundaries.
      - If Auto OFF ("true" => False) arrives, stop immediately and exit.
    """
    force_all_off()

    # Wait for initial ON signal
    while True:
        sw = read_payload()
        if sw is True:
            break
        if sw is False:
            force_all_off()
            emit({"type": "status", "status": "stopped", "reason": "initial_switch_off"})
            return
        time.sleep(0.1)

    last_run_slot = None

    try:
        while True:
            sw = read_payload()
            if sw is False:
                force_all_off()
                emit({"type": "status", "status": "stopped", "reason": "switch_off"})
                break

            now = datetime.datetime.now()

            if is_on_boundary(now):
                cur_slot = slot_stamp(now)
                if cur_slot != last_run_slot:
                    res = control_once_from_csv()
                    if res == "STOP":
                        break
                    last_run_slot = cur_slot

            time.sleep(POLL_SEC)

    finally:
        force_all_off()

if __name__ == "__main__":
    main_loop()
