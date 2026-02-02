# -*- coding: utf-8 -*-
import os
import json
import time
import datetime
import serial
import fcntl
import sqlite3
from serial.serialutil import SerialException

# ===============================
# Settings
# ===============================
PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
BAUD = 115200
REQ  = "node000000|SensorReq|0905"

# SQLite
DB_PATH = "/home/cja/Work/cja-skyfarms-project/data/data.db"
DB_TABLE = "Temp_humi_log"

# Sensor IDs
ID_TEMPERATURE = 1
ID_HUMIDITY    = 2
ID_CO2         = 6

# Lock (prevent concurrent access to same USB serial)
SERIAL_LOCK_PATH = "/tmp/usb_1a86_serial.lock"

# Timings
PRINT_EVERY_SEC = 10      # JSON output every 10 sec
SAVE_EVERY_MIN  = 20      # DB save every 20 min (00/20/40) - robust slot based

# Read burst tuning
READ_TIMEOUT_SEC = 2.5
IDLE_GAP_SEC = 0.2
RETRY_ATTEMPTS = 3
RETRY_DELAY_SEC = 0.25


# ===============================
# Timing (no drift)
# ===============================
def sleep_to_next_boundary(step_sec: int):
    """Sleep until the next wall-clock boundary (no drift)."""
    now = time.time()
    next_t = (int(now) // step_sec + 1) * step_sec
    time.sleep(max(0, next_t - now))


def minute_key(dt: datetime.datetime) -> str:
    """YYYY-MM-DD HH:MM"""
    return dt.strftime("%Y-%m-%d %H:%M")


def slot_key_for(dt: datetime.datetime, step_min: int) -> str:
    """
    Return slot key "YYYY-MM-DD HH:MM" floored to step minutes.
    Example: 13:20:55 with step=20 -> 13:20
    """
    slot_min = (dt.minute // step_min) * step_min
    slot_dt = dt.replace(minute=slot_min, second=0, microsecond=0)
    return slot_dt.strftime("%Y-%m-%d %H:%M")


# ===============================
# Serial helpers
# ===============================
def read_one_response(ser, timeout=2.5, idle_gap=0.2) -> bytes:
    """Read until no more bytes arrive for a short idle gap (no newline protocol)."""
    ser.timeout = idle_gap
    buf = bytearray()
    t0 = time.time()
    last_rx = None

    while time.time() - t0 < timeout:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            last_rx = time.time()
        else:
            if buf and last_rx and (time.time() - last_rx) > idle_gap:
                break

    return bytes(buf)


def extract_json_block(text: str):
    """Extract {...} part from '|SensorRes|{...}|XXXX'."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end + 1]


def get_value_by_id(data: dict, target_id: int):
    """Return float value for sensor id, or None."""
    for s in data.get("sensors", []):
        if s.get("id") == target_id:
            v = str(s.get("value", "")).strip()
            try:
                return float(v)
            except Exception:
                return None
    return None


def read_sensor_once():
    """Single attempt: open port, send request, read response, parse values."""
    with serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0.2) as ser:
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        ser.write(REQ.encode("ascii", errors="ignore"))
        ser.flush()

        raw = read_one_response(ser, timeout=READ_TIMEOUT_SEC, idle_gap=IDLE_GAP_SEC)

    text = raw.replace(b"\x00", b"").decode("utf-8", errors="replace").strip()
    json_part = extract_json_block(text)
    if not json_part:
        return None, None, None, "no_json_block"

    try:
        data = json.loads(json_part)
    except Exception as e:
        return None, None, None, f"json_load_error: {e}"

    temperature = get_value_by_id(data, ID_TEMPERATURE)
    humidity = get_value_by_id(data, ID_HUMIDITY)
    co2 = get_value_by_id(data, ID_CO2)

    # Accept only when ALL exist (stickiness handled in main)
    if temperature is None or humidity is None or co2 is None:
        return temperature, humidity, co2, "value_missing"

    return temperature, humidity, co2, None


def read_sensor_with_lock_and_retry():
    """Prevent concurrent access + retry a few times for stability."""
    lockf = open(SERIAL_LOCK_PATH, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX)

        last_err = None
        last_vals = (None, None, None)

        for _ in range(RETRY_ATTEMPTS):
            try:
                t, h, c, err = read_sensor_once()
                last_vals = (t, h, c)
                last_err = err
                if err is None:
                    return t, h, c, None
            except (SerialException, OSError) as e:
                last_err = f"serial_error: {e}"
            except Exception as e:
                last_err = f"unknown_error: {e}"

            time.sleep(RETRY_DELAY_SEC)

        return last_vals[0], last_vals[1], last_vals[2], last_err

    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        except Exception:
            pass
        lockf.close()


# ===============================
# SQLite helpers
# ===============================
def ensure_db_schema(db_path: str, table: str):
    """Create table/index if not exists. Keep schema with CAPITAL column names."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")

        # Match your actual schema: Date/Temperature/Humidity/CO2
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{table}" (
                "Date" TEXT,
                "Temperature" REAL,
                "Humidity" REAL,
                "CO2" INTEGER
            );
        """)
        conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_date" ON "{table}"("Date");')
        conn.commit()
    finally:
        conn.close()


def insert_room_condition(db_path: str, table: str, date_str: str, temperature, humidity, co2):
    """Insert one row (Date/Temperature/Humidity/CO2)."""
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(
            f'INSERT INTO "{table}" ("Date","Temperature","Humidity","CO2") VALUES (?,?,?,?);',
            (date_str, temperature, humidity, int(co2) if co2 is not None else None)
        )
        conn.commit()
    finally:
        conn.close()


# ===============================
# Main (continuous)
# ===============================
def main():
    ensure_db_schema(DB_PATH, DB_TABLE)

    # Stickiness (last good values)
    latest_t = None
    latest_h = None
    latest_c = None
    latest_err = None

    # Save guard (prevent duplicate save within the same slot)
    last_saved_slot = None

    while True:
        # 1) Run on exact 10-second boundaries
        sleep_to_next_boundary(PRINT_EVERY_SEC)

        t, h, c, err = read_sensor_with_lock_and_retry()

        # Update latest only when sample is complete and valid
        if err is None and t is not None and h is not None and c is not None:
            latest_t, latest_h, latest_c = float(t), float(h), float(c)
            latest_err = None
        else:
            latest_err = err

        now = datetime.datetime.now()
        mkey = minute_key(now)

        # Prepare output (single-line JSON only)
        out = {
            "date": mkey,
            "temperature": latest_t,
            "humidity": latest_h,
            "co2": latest_c,
            "errors": {
                "sensor": latest_err,
                "db": None
            },
            "save": {
                "every_min": SAVE_EVERY_MIN,
                "slot": None,
                "did": False
            }
        }

        # 2) Robust slot-based save (independent of second timing)
        #    Save ONCE per slot, but only when we're inside a boundary minute.
        #    Example: any time during 13:20:xx counts as the "13:20" slot.
        if now.minute % SAVE_EVERY_MIN == 0:
            skey = slot_key_for(now, SAVE_EVERY_MIN)
            out["save"]["slot"] = skey

            if last_saved_slot != skey:
                if latest_t is None or latest_h is None or latest_c is None:
                    out["errors"]["db"] = "skip_save: latest values are None"
                else:
                    try:
                        insert_room_condition(DB_PATH, DB_TABLE, skey, latest_t, latest_h, latest_c)
                        last_saved_slot = skey
                        out["save"]["did"] = True
                    except Exception as e:
                        out["errors"]["db"] = f"db_write_failed: {e}"

        print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
