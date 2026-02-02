# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import sqlite3
import datetime
import select
import serial
import fcntl
import re
import math
from serial.serialutil import SerialException

# ===============================
# 1. Settings
# ===============================
PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
BAUD = 115200
REQ  = "node000300|SensorReq|8985"
SERIAL_LOCK_PATH = "/tmp/usb_1a86_serial.lock"

# Database for logging only
DB_PATH = "/home/cja/Work/cja-skyfarms-project/data/data.db"
DB_TABLE = "Dist_2_EC_pH_log"

# Schedule mode: "30min" / "1hour" / "4hour" (default)
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
POLL_SEC = 0.5
TOTAL_TIMEOUT_SEC = 3.0
IDLE_GAP_SEC = 0.2
RETRY_ATTEMPTS = 3
RETRY_DELAY_SEC = 0.25

# Reading Strategy: Take 3 samples to find representative values
READ_N = 3
READ_GAP_SEC = 0.2

# Valid Sensor Ranges (Physical safety limits)
VALID_EC_MIN, VALID_EC_MAX = 0.00, 3.00
VALID_PH_MIN, VALID_PH_MAX = 3.50, 10.00
VALID_TP_MIN, VALID_TP_MAX = 10.00, 50.00

# Sensor IDs
ID_PH   = 16
ID_TEMP = 29
ID_EC   = 30

# ===============================
# 2. Timing and Scheduling
# ===============================
def now_dt() -> datetime.datetime:
    return datetime.datetime.now()

def now_str(include_sec=True) -> str:
    fmt = "%Y-%m-%d %H:%M:%S" if include_sec else "%Y-%m-%d %H:%M"
    return now_dt().strftime(fmt)

def slot_stamp(dt: datetime.datetime) -> str:
    """Generate a unique ID for the current time slot based on mode."""
    dt0 = dt.replace(second=0, microsecond=0)
    if SCHEDULE_MODE == "30min":
        mm = 0 if dt0.minute < 30 else 30
        return dt0.strftime("%Y%m%d%H") + f"{mm:02d}"
    elif SCHEDULE_MODE == "1hour":
        return dt0.strftime("%Y%m%d%H")
    else: # 4hour (00, 04, 08, 12, 16, 20)
        hh = (dt0.hour // 4) * 4
        return dt0.strftime("%Y%m%d") + f"{hh:02d}"

# ===============================
# 3. Node-RED Communication (I/O)
# ===============================
def read_auto_mode_status():
    """Read Auto Mode status from Node-RED stdin (Non-blocking)."""
    if select.select([sys.stdin], [], [], 0)[0]:
        raw = sys.stdin.readline().strip().lower()
        if raw == "true": return False # Auto Mode OFF
        if raw == "false": return True # Auto Mode ON
    return None

def emit(obj):
    """Output JSON string to stdout for Node-RED processing."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)

def gpio_cmd(topic: str, value: int):
    """Send GPIO control command to Node-RED."""
    emit({"type": "gpio", "topic": topic, "payload": int(value)})

def stop_all_pumps():
    """Safety: Force turn off all pumps."""
    gpio_cmd(TOPIC_AB, GPIO_OFF)
    gpio_cmd(TOPIC_ACID, GPIO_OFF)

# ===============================
# 4. Database Persistence (Logging)
# ===============================
def ensure_db_initialized(path: str):
    """Create table and index if they don't exist."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{DB_TABLE}" (
                "Date" TEXT, "EC" REAL, "pH" REAL, "Solution_Temperature" REAL
            );
        """)
        conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_d2_date" ON "{DB_TABLE}"("Date");')
        conn.commit()
    finally: conn.close()

def log_to_db(date_str, ec, ph, tp):
    """Write validated sensor results to the SQLite file."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(f'INSERT INTO "{DB_TABLE}" VALUES (?,?,?,?);', (date_str, ec, ph, tp))
        conn.commit()
    finally: conn.close()

# ===============================
# 5. Sensor Data Acquisition
# ===============================
def parse_raw_serial(text: str):
    """Extract float values from the custom serial response format."""
    def extract_id(t: str, tid: int):
        m = re.search(r'(?:\"?id\"?)\s*[:=]\s*\"?' + re.escape(str(tid)) + r'\"?', t, re.IGNORECASE)
        if not m: return None
        sub = t[m.start(): m.start() + 260]
        mv = re.search(r'(?:\"?value\"?)\s*[:=]\s*\"?\s*([0-9]+(?:[./][0-9]+)?)\s*\"?', sub, re.IGNORECASE)
        if mv:
            val_str = mv.group(1).replace("/", ".")
            return float(val_str) if math.isfinite(float(val_str)) else None
        return None
    return extract_id(text, ID_EC), extract_id(text, ID_PH), extract_id(text, ID_TEMP)

def fetch_sensor_data():
    """Request data from serial port with file locking."""
    lockf = open(SERIAL_LOCK_PATH, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        with serial.Serial(PORT, baudrate=BAUD, timeout=0.1) as ser:
            time.sleep(0.15)
            ser.reset_input_buffer()
            ser.write(REQ.encode("ascii"))
            ser.flush()
            
            buf = bytearray()
            t0 = time.time()
            while time.time() - t0 < TOTAL_TIMEOUT_SEC:
                chunk = ser.read(256)
                if chunk: buf += chunk
                elif buf: break
            return parse_raw_serial(buf.decode("utf-8", errors="replace"))
    except: return None, None, None
    finally:
        fcntl.flock(lockf, fcntl.LOCK_UN)
        lockf.close()

# ===============================
# 6. Control Execution Logic
# ===============================
def run_control_sequence():
    """Core logic: Read 3 times -> check validity (at least 2/3) -> Decision -> Action."""
    ec_samples, ph_samples, tp_samples = [], [], []
    
    # Collect 3 samples for robustness
    for _ in range(READ_N):
        e, p, t = fetch_sensor_data()
        if e is not None and VALID_EC_MIN <= e <= VALID_EC_MAX: ec_samples.append(e)
        if p is not None and VALID_PH_MIN <= p <= VALID_PH_MAX: ph_samples.append(p)
        if t is not None and VALID_TP_MIN <= t <= VALID_TP_MAX: tp_samples.append(t)
        time.sleep(READ_GAP_SEC)

    # Success condition: At least 2 valid reads out of 3 for EC and Temp
    if len(ec_samples) < 2 or len(tp_samples) < 2:
        emit({"type": "status", "status": "fail", "reason": "insufficient_valid_samples"})
        return "FAIL"

    # Use median to pick the most representative value
    def get_median(lst): return sorted(lst)[len(lst)//2]
    rep_ec = round(get_median(ec_samples), 2)
    rep_ph = round(get_median(ph_samples), 2) if ph_samples else None
    rep_tp = round(get_median(tp_samples), 2)

    # 1. Log the result to DB for charting
    log_to_db(now_str(False), rep_ec, rep_ph, rep_tp)

    # 2. Injection logic for AB (Nutrients)
    if rep_ec <= EC_MIN:
        duration = DOSE_ML / PUMP_ML_PER_SEC
        gpio_cmd(TOPIC_AB, GPIO_ON)
        time.sleep(duration)
        gpio_cmd(TOPIC_AB, GPIO_OFF)
        emit({"type":"log", "device":"AB", "payload": f"{now_str()},AB,vol,{DOSE_ML},dur,{round(duration,1)}s"})

    # 3. Injection logic for Acid (pH control)
    if rep_ph and rep_ph >= PH_MAX:
        duration = DOSE_ML / PUMP_ML_PER_SEC
        gpio_cmd(TOPIC_ACID, GPIO_ON)
        time.sleep(duration)
        gpio_cmd(TOPIC_ACID, GPIO_OFF)
        emit({"type":"log", "device":"Acid", "payload": f"{now_str()},Acid,vol,{DOSE_ML},dur,{round(duration,1)}s"})

    emit({"type": "status", "status": "ok", "ec": rep_ec, "ph": rep_ph, "temp": rep_tp})
    return "OK"

# ===============================
# 7. Main Loop
# ===============================
def main():
    ensure_db_initialized(DB_PATH)
    stop_all_pumps()
    
    # Initial Wait for Auto Mode Signal from Node-RED
    while True:
        if read_auto_mode_status() is True: break
        time.sleep(0.1)

    # FIX: Set current slot as 'already run' on start to prevent immediate execution
    last_run_slot = slot_stamp(now_dt()) 
    
    emit({"type": "started", "mode": SCHEDULE_MODE, "first_scheduled_slot_after": last_run_slot})

    try:
        while True:
            # Emergency Stop if Auto Mode is switched OFF
            if read_auto_mode_status() is False:
                stop_all_pumps()
                emit({"type": "status", "status": "stopped", "reason": "manual_switch_off"})
                break

            now = now_dt()
            current_slot = slot_stamp(now)

            # Trigger only when entering a NEW time slot
            if current_slot != last_run_slot:
                run_control_sequence()
                last_run_slot = current_slot

            time.sleep(POLL_SEC)
    finally:
        stop_all_pumps()

if __name__ == "__main__":
    main()