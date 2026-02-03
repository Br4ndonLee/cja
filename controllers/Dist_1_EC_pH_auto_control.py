# -*- coding: utf-8 -*-
import time
import json
import datetime
import minimalmodbus
import serial
import fcntl
import sys
import select
import sqlite3

# ===============================
# Settings
# ===============================

# RS485 (Modbus RTU) port and slave address for EC/pH sensor
EC_PH_PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0"
SLAVE_ID = 1

# SQLite (solution input log)
SOLUTION_DB_PATH = "/home/cja/Work/cja-skyfarms-project/data/data.db"
SOLUTION_DB_TABLE = "Dist_1_Solution_input_log"
# Averaging window settings
DURATION_SEC = 20
INTERVAL_SEC = 1

# ===============================
# Schedule mode
# ===============================
# TEST: run at every HH:00 and HH:30 (minute boundary)
# PROD: run at every 4 hours (00/04/08/12/16/20) at HH:00 only
# SCHEDULE_MODE = "30min"   # "30min" or "4hour"

# 20260127 JeongMin edit
SCHEDULE_MODE = "4hour" # Production setting

# Thresholds
EC_MIN = 1.1
PH_MAX = 6.1

# Pump dosing volume
DOSE_ML = 5.0
# ==============================================================

# Pump calibration (ml per second)
PUMP_ML_PER_SEC = 1.65

# Node-RED GPIO topics (these map to your rpi-gpio out nodes)
TOPIC_AB = "GPIO17"   # AB pump relay
TOPIC_ACID = "GPIO21" # Acid pump relay

# Active-low relay: 0=ON, 1=OFF
GPIO_ON = 0
GPIO_OFF = 1

# ===============================
# Node-RED switch (stdin) handling
# ===============================
def read_payload():
    """
    Non-blocking stdin read for Node-RED pythonshell input.
    Expected values:
      - "false"  -> keep running (Auto ON)
      - "true" -> stop immediately (Auto OFF)
    Because fucking Raspberry Pi's stdin is inverted GPIO.
    Returns:
      True / False / None (if no new input)
    """
    if select.select([sys.stdin], [], [], 0)[0]:
        raw = sys.stdin.readline().strip().lower()
        if raw == "true":
            return False
        if raw == "false":
            return True
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

def now_str(sec=True) -> str:
    """Return current timestamp string."""
    fmt = "%Y-%m-%d %H:%M:%S" if sec else "%Y-%m-%d %H:%M"
    return datetime.datetime.now().strftime(fmt)

# ===============================
# Modbus setup
# ===============================
dev = minimalmodbus.Instrument(EC_PH_PORT, SLAVE_ID, mode="rtu")
dev.serial.baudrate = 9600
dev.serial.bytesize = 8
dev.serial.parity   = serial.PARITY_NONE
dev.serial.stopbits = 2
dev.serial.timeout  = 1
dev.clear_buffers_before_each_transaction = True

# ===============================
# Sensor read
# ===============================
def safe_read_once():
    """
    Read EC, pH, and solution temperature once.
    Returns:
      (ec, ph, temp) as floats, or (None, None, None) if read fails.
    """
    try:
        ph_raw = dev.read_register(0x00, 2, functioncode=3)
        ec_raw = dev.read_register(0x01, 2, functioncode=3) / 10.0
        temp_raw = dev.read_register(0x02, 2, functioncode=3) * 10.0
        return float(ec_raw), float(ph_raw), float(temp_raw)
    except Exception:
        return None, None, None

def average_ec_ph_temp():
    """
    Collect readings for DURATION_SEC and return averaged values.
    Also checks switch OFF during averaging and aborts immediately.
    Returns:
      ("OK", avg_ec, avg_ph, avg_temp)
      ("FAIL", None, None, None) on sensor read failure
      ("STOP", None, None, None) if switch turned OFF
    """
    ec_list, ph_list, temp_list = [], [], []
    start = time.monotonic()
    next_tick = start

    while True:
        sw = read_payload()
        if sw is False:
            return "STOP", None, None, None

        ec, ph, temp = safe_read_once()
        if ec is not None and ph is not None and temp is not None:
            ec_list.append(ec)
            ph_list.append(ph)
            temp_list.append(temp)

        if time.monotonic() - start >= DURATION_SEC:
            break

        next_tick += INTERVAL_SEC
        time.sleep(max(0, next_tick - time.monotonic()))

    if not ec_list or not ph_list or not temp_list:
        return "FAIL", None, None, None

    avg_ec = round(sum(ec_list) / len(ec_list), 2)
    avg_ph = round(sum(ph_list) / len(ph_list), 2)
    avg_temp = round(sum(temp_list) / len(temp_list), 2)

    return "OK", avg_ec, avg_ph, avg_temp

def fmt_num(x: float) -> str:
    """Format numbers: 2.0 -> '2', 2.5 -> '2.5'."""
    try:
        xf = float(x)
    except Exception:
        return str(x)
    if abs(xf - round(xf)) < 1e-9:
        return str(int(round(xf)))
    # Keep compact representation (e.g., 2.5, 1.23)
    return f"{xf:g}"

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
        if sw is False:
            raise RuntimeError("auto_switch_off")
        time.sleep(0.05)
        
def run_pump_via_nodered(topic: str, device_name: str, ml: float, sec_needed: float):
    """
    Run pump by emitting GPIO ON/OFF, and emit a log line object to Node-RED.
    """
    # ON
    gpio(topic, GPIO_ON)

    try:
        wait_with_abort(sec_needed)
    finally:
        # Always OFF
        gpio(topic, GPIO_OFF)

    # Emit log line (Node-RED will append newline in file node)
    ts = now_str(sec=True)
    sec_disp = round(sec_needed, 1)

    line = f"{ts},{device_name},volume,{fmt_num(ml)},duration,{fmt_num(sec_disp)}s"
    emit({"type": "log", "device": device_name, "payload": line})
    try:
        db_insert_solution(ts, device_name, ml, sec_needed)
    except Exception as e:
        emit({"type": "db_error", "where": "run_pump_via_nodered", "error": str(e)})


def db_insert_solution(ts: str, device_name: str, ml: float, sec_needed: float):
    with sqlite3.connect(SOLUTION_DB_PATH, timeout=5) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            f"""
            INSERT INTO {SOLUTION_DB_TABLE}
            (Date, device, action, detail)
            VALUES (?, ?, ?, ?)
            """,
            (
                ts,
                device_name,
                "volume",
                float(ml),
            ),
        )
# ===============================
# One control cycle
# ===============================
def control_once():
    """
    One control cycle:
      1) Lock RS485 bus
      2) Read averaged EC/pH/temp
      3) If EC < EC_MIN -> dose AB
         If pH >= PH_MAX -> dose Acid
    NOTE: GPIO is controlled by Node-RED using emitted JSON commands.
    """
    lock = open("/tmp/rs485_bus.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)

    try:
        status, avg_ec, avg_ph, avg_temp = average_ec_ph_temp()

        if status == "STOP":
            # Do not spam logs; just stop cleanly
            return "STOP"

        if status == "FAIL" or avg_ec is None:
            # Keep quiet or emit a minimal error if you want:
            # emit({"type":"log","device":"AB","payload":f"{now_str(True)},SYS,error,sensor_read_failed"})
            return "FAIL"

        sec_needed = DOSE_ML / PUMP_ML_PER_SEC

        # Control logic
        if avg_ec <= EC_MIN:
            run_pump_via_nodered(TOPIC_AB, "AB", DOSE_ML, sec_needed)

        if avg_ph >= PH_MAX:
            run_pump_via_nodered(TOPIC_ACID, "Acid", DOSE_ML, sec_needed)

        return "OK"

    except Exception as e:
        if str(e) == "auto_switch_off":
            force_all_off()
            return "STOP"
        # For safety, force OFF on any unexpected error
        force_all_off()
        return "FAIL"

    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        except:
            pass

def is_on_boundary(dt: datetime.datetime) -> bool:
    """
    Decide whether current time is on the schedule boundary.
    - 30min: minute is 0 or 30
    - 4hour: hour is multiple of 4 AND minute is 0
    """
    if SCHEDULE_MODE == "30min":
        return (dt.minute % 30 == 0)
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

    # "4hour"
    hh = (dt0.hour // 4) * 4
    return dt0.strftime("%Y%m%d") + f"{hh:02d}"


# ===============================
# Main loop
# ===============================
def main_loop():
    """
    Controller-style stdin control:
      - Wait until we receive "true" (Auto ON) to start.
      - Run control_once ONLY at predictable wall-clock boundaries:
          * TEST  ("30min"): every HH:00 and HH:30
          * PROD  ("4hour"): every 4 hours at HH:00 (00/04/08/12/16/20)
      - No requirement to hit second==00. Runs once within that boundary minute.
      - Duplicate runs inside the same boundary minute are prevented by slot_stamp().
      - If "false" arrives, stop immediately and force pumps OFF.
    """
    # Ensure OFF at boot
    force_all_off()

    # Wait for initial ON signal
    while True:
        sw = read_payload()
        if sw is True:
            break
        if sw is False:
            force_all_off()
            return
        time.sleep(0.1)

    # Track last executed slot to avoid duplicate execution within same boundary minute
    last_run_slot = None

    try:
        while True:
            # Check OFF quickly
            sw = read_payload()
            if sw is False:
                force_all_off()
                break

            now = datetime.datetime.now()

            # Run only on boundary and only once per slot
            if is_on_boundary(now):
                cur_slot = slot_stamp(now)
                if cur_slot != last_run_slot:
                    res = control_once()
                    if res == "STOP":
                        break
                    last_run_slot = cur_slot

            # Polling interval: small enough to not miss the boundary minute
            # (00/30 or 00) but not too busy. 0.2~1.0s are fine.
            time.sleep(0.2)

    finally:
        force_all_off()


if __name__ == "__main__":
    main_loop()
