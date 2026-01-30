# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import csv
import datetime
import select
import serial
import fcntl
import re
import math
from serial.serialutil import SerialException

# ===============================
# Settings
# ===============================
PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
BAUD = 115200
REQ  = "node000300|SensorReq|8985"
SERIAL_LOCK_PATH = "/tmp/usb_1a86_serial.lock"

# Target sensor IDs
ID_PH   = 16
ID_TEMP = 29
ID_EC   = 30

# Path for logging sensor snapshots
SENSOR_CSV = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_2_EC_pH_log.csv"

# Schedule mode: "30min" / "1hour" / "4hour"
SCHEDULE_MODE = "4hour"

# Control Thresholds
EC_MIN = 1.1
PH_MAX = 6.1

# Pump Settings
DOSE_ML = 50.0
PUMP_ML_PER_SEC = 1.65
TOPIC_AB = "GPIO22"
TOPIC_ACID = "GPIO23"

# GPIO Logic: 0 is ON, 1 is OFF
GPIO_ON = 0
GPIO_OFF = 1

# Timing Constants
POLL_SEC = 0.2
TOTAL_TIMEOUT_SEC = 3.0
IDLE_GAP_SEC = 0.2
RETRY_ATTEMPTS = 3
RETRY_DELAY_SEC = 0.25

# Reading Strategy
READ_N = 3
READ_GAP_SEC = 0.15

# Valid Sensor Ranges
VALID_EC_MIN, VALID_EC_MAX = 0.00, 3.00
VALID_PH_MIN, VALID_PH_MAX = 3.50, 10.00
VALID_TP_MIN, VALID_TP_MAX = 10.00, 50.00

# ===============================
# Node-RED Communication
# ===============================
def read_payload():
    """
    Non-blocking read from stdin for Node-RED interaction.
    'false' (as string) means Auto Mode ON.
    'true' (as string) means Auto Mode OFF.
    """
    if select.select([sys.stdin], [], [], 0)[0]:
        raw = sys.stdin.readline().strip().lower()
        if raw == "true":
            return False
        if raw == "false":
            return True
    return None

def emit(obj):
    """Output JSON string to stdout for Node-RED."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)

def gpio(topic: str, value: int):
    """Send GPIO control command and debug log to Node-RED."""
    emit({"type": "gpio", "topic": topic, "payload": int(value)})
    emit({"type": "dbg", "what": "gpio_sent", "topic": topic, "payload": int(value)})

def force_all_off():
    """Safety: Turn off all pumps immediately."""
    gpio(TOPIC_AB, GPIO_OFF)
    gpio(TOPIC_ACID, GPIO_OFF)

# ===============================
# Scheduling Helpers
# ===============================
def now_dt() -> datetime.datetime:
    return datetime.datetime.now()

def now_str(sec=True) -> str:
    fmt = "%Y-%m-%d %H:%M:%S" if sec else "%Y-%m-%d %H:%M"
    return now_dt().strftime(fmt)

def slot_stamp(dt: datetime.datetime) -> str:
    """
    Generates a unique ID for the current time slot based on SCHEDULE_MODE.
    This ensures the code runs exactly once per interval.
    """
    dt0 = dt.replace(second=0, microsecond=0)
    if SCHEDULE_MODE == "30min":
        mm = 0 if dt0.minute < 30 else 30
        return dt0.strftime("%Y%m%d%H") + f"{mm:02d}"
    if SCHEDULE_MODE == "1hour":
        return dt0.strftime("%Y%m%d%H")
    # 4-hour slots: 00, 04, 08, 12, 16, 20
    hh = (dt0.hour // 4) * 4
    return dt0.strftime("%Y%m%d") + f"{hh:02d}"

# ===============================
# CSV Data Logging
# ===============================
def ensure_csv_header(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if (not os.path.exists(path)) or (os.path.getsize(path) == 0):
        with open(path, mode="a", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Date", "EC", "pH", "Solution_Temperature"])
            f.flush()
            os.fsync(f.fileno())

def append_sensor_row(path: str, date_str: str, ec, ph, tp):
    with open(path, mode="a", newline="") as f:
        w = csv.writer(f)
        w.writerow([date_str, ec, ph, tp])
        f.flush()
        os.fsync(f.fileno())

# ===============================
# Serial Communication & Parsing
# ===============================
def read_burst(ser, total_timeout=3.0, idle_gap=0.2) -> bytes:
    ser.timeout = 0.1
    buf = bytearray()
    t0 = time.time()
    last_rx = None

    while time.time() - t0 < total_timeout:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            last_rx = time.time()
        else:
            if buf and last_rx and (time.time() - last_rx) > idle_gap:
                break
    return bytes(buf)

def safe_decode(raw: bytes) -> str:
    raw = raw.replace(b"\x00", b"")
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()

def fix_slash_number(s: str) -> str:
    s = s.strip()
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return parts[0] + "." + parts[1]
    return s

def to_float_maybe(s: str):
    if s is None: return None
    s2 = fix_slash_number(str(s))
    s2 = s2.replace(" ", "")
    s2 = re.sub(r"[^0-9\.\-]", "", s2)
    if not s2: return None
    try:
        v = float(s2)
        return v if math.isfinite(v) else None
    except:
        return None

def parse_ec_ph_tp(text: str):
    """Parse sensor values by searching for specific IDs in the response string."""
    def extract_for_id(t: str, target_id: int):
        m = re.search(r'(?:\"?id\"?)\s*[:=]\s*\"?' + re.escape(str(target_id)) + r'\"?', t, re.IGNORECASE)
        if not m: return None
        window = t[m.start(): m.start() + 260]
        mv = re.search(r'(?:\"?value\"?)\s*[:=]\s*\"?\s*([0-9]+(?:[./][0-9]+)?)\s*\"?', window, re.IGNORECASE)
        if mv: return to_float_maybe(mv.group(1))
        mn = re.search(r'([0-9]+(?:[./][0-9]+)?)', window)
        return to_float_maybe(mn.group(1)) if mn else None

    ph = extract_for_id(text, ID_PH)
    tp = extract_for_id(text, ID_TEMP)
    ec = extract_for_id(text, ID_EC)
    return ec, ph, tp

def request_once_locked():
    """Request data from sensor. Must be called within a file lock context."""
    last_err = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            with serial.Serial(PORT, baudrate=BAUD, timeout=0.1) as ser:
                time.sleep(0.15)
                ser.reset_input_buffer()
                ser.write(REQ.encode("ascii", errors="ignore"))
                ser.flush()
                raw = read_burst(ser, total_timeout=TOTAL_TIMEOUT_SEC, idle_gap=IDLE_GAP_SEC)
                if not raw:
                    last_err = "no_data"
                    continue
                ec, ph, tp = parse_ec_ph_tp(safe_decode(raw))
                if ec is None and ph is None and tp is None:
                    last_err = "value_missing_all"
                    continue
                return ec, ph, tp, None
        except Exception as e:
            last_err = str(e)
            time.sleep(RETRY_DELAY_SEC)
    return None, None, None, last_err

# ===============================
# Data Processing (Median Filter)
# ===============================
def valid_range(x, lo, hi) -> bool:
    try:
        return math.isfinite(float(x)) and (lo <= float(x) <= hi)
    except:
        return False

def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0: return None
    mid = n // 2
    return s[mid] if n % 2 == 1 else 0.5 * (s[mid - 1] + s[mid])

def read_representative_3():
    """Perform 3 reads and return median values to filter out noise."""
    lockf = open(SERIAL_LOCK_PATH, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        ec_list, ph_list, tp_list = [], [], []
        for i in range(READ_N):
            sw = read_payload()
            if sw is False: return "STOP", None, None, None
            ec, ph, tp, err = request_once_locked()
            if err is None:
                if valid_range(ec, VALID_EC_MIN, VALID_EC_MAX): ec_list.append(float(ec))
                if valid_range(ph, VALID_PH_MIN, VALID_PH_MAX): ph_list.append(float(ph))
                if valid_range(tp, VALID_TP_MIN, VALID_TP_MAX): tp_list.append(float(tp))
            if i < READ_N - 1: time.sleep(READ_GAP_SEC)
            
        if len(ec_list) < 2 or len(tp_list) < 2:
            return "FAIL", None, None, None
            
        return "OK", round(median(ec_list), 2), (round(median(ph_list), 2) if ph_list else None), round(median(tp_list), 2)
    finally:
        fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()

# ===============================
# Control & Execution
# ===============================
def wait_with_abort(seconds: float):
    """Wait for pump duration while checking if user turned off Auto mode."""
    t0 = time.monotonic()
    while (time.monotonic() - t0) < max(0.0, seconds):
        if read_payload() is False:
            raise RuntimeError("auto_switch_off")
        time.sleep(0.05)

def run_pump(topic: str, device: str, ml: float):
    sec_needed = ml / PUMP_ML_PER_SEC
    gpio(topic, GPIO_ON)
    try:
        wait_with_abort(sec_needed)
    finally:
        gpio(topic, GPIO_OFF)
    line = f"{now_str(True)},{device},volume,{ml},duration,{round(sec_needed,1)}s"
    emit({"type": "log", "device": device, "payload": line})

def control_once_direct():
    """Main control logic: Read sensors -> Logic Check -> Pump Control."""
    status, ec, ph, tp = read_representative_3()
    if status == "STOP":
        force_all_off()
        emit({"type": "status", "status": "stopped", "reason": "switch_off_during_read"})
        return "STOP"
    if status == "FAIL":
        emit({"type": "status", "status": "fail", "reason": "rep_read_failed"})
        return "FAIL"

    try:
        ensure_csv_header(SENSOR_CSV)
        append_sensor_row(SENSOR_CSV, now_str(False), ec, (ph if ph is not None else ""), tp)
    except: pass

    try:
        # Check EC logic
        if ec <= EC_MIN:
            run_pump(TOPIC_AB, "AB", DOSE_ML)
        # Check pH logic
        if (ph is not None) and (ph >= PH_MAX):
            run_pump(TOPIC_ACID, "Acid", DOSE_ML)

        emit({"type": "status", "status": "ok", "ec": ec, "ph": ph, "temp": tp})
        return "OK"
    except RuntimeError as e:
        force_all_off()
        emit({"type": "status", "status": "stopped", "reason": str(e)})
        return "STOP"
    except Exception:
        force_all_off()
        emit({"type": "status", "status": "fail", "reason": "unexpected_error"})
        return "FAIL"

# ===============================
# Main Loop
# ===============================
def main_loop():
    force_all_off()
    
    # Wait for Initial ON Signal
    while True:
        sw = read_payload()
        if sw is True: break
        time.sleep(0.1)

    last_run_slot = None
    emit({"type": "started", "mode": SCHEDULE_MODE, "read": f"{READ_N}x_median"})

    try:
        while True:
            # Check if Auto mode is switched OFF
            sw = read_payload()
            if sw is False:
                force_all_off()
                emit({"type": "status", "status": "stopped", "reason": "switch_off"})
                break

            now = now_dt()
            cur_slot = slot_stamp(now)

            # Slot-based execution logic
            # This triggers as soon as the current time enters a new 30m/1h/4h slot
            if cur_slot != last_run_slot:
                res = control_once_direct()
                if res == "STOP": break
                # Even if FAIL, we mark the slot as run to avoid infinite retry loops 
                # within the same second/minute.
                last_run_slot = cur_slot

            time.sleep(POLL_SEC)
    finally:
        force_all_off()

if __name__ == "__main__":
    main_loop()