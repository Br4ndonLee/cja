# -*- coding: utf-8 -*-
import os
import json
import time
import datetime
import serial
import fcntl
import sqlite3
import re
import math
from serial.serialutil import SerialException

# ===============================
# Settings
# ===============================
PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
BAUD = 115200
REQ  = "node000300|SensorReq|8985"

DB_PATH = "/home/cja/Work/cja-skyfarms-project/data/data.db"
DB_TABLE = "Dist_2_EC_pH_log"

SERIAL_LOCK_PATH = "/tmp/usb_1a86_serial.lock"

# Poll / report / save
POLL_SEC = 10           # JSON output every 10 sec
DB_EVERY_MIN = 20       # save every 15 min (00/15/30/45)

# Physical validity ranges (safe)
VALID_EC_MIN, VALID_EC_MAX = 0.00, 3.00        # dS/m
VALID_PH_MIN, VALID_PH_MAX = 3.50, 10.00       # pH
VALID_TP_MIN, VALID_TP_MAX = 10.00, 50.00      # °C

# Sensor IDs
ID_PH   = 16
ID_TEMP = 29
ID_EC   = 30

# Read burst tuning
TOTAL_TIMEOUT_SEC = 3.0
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


# ===============================
# Serial helpers
# ===============================
def read_burst(ser, total_timeout=3.0, idle_gap=0.2) -> bytes:
    """Read bytes until idle gap after some data (no newline protocol)."""
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
    """Decode even if bytes are broken; strip control chars."""
    raw = raw.replace(b"\x00", b"")
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.strip()

def extract_json_block(text: str):
    """Extract {...} from '|SensorRes|{...}|XXXX'."""
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
                x = float(v)
                return x if math.isfinite(x) else None
            except Exception:
                return None
    return None


# ===============================
# Validity checks
# ===============================
def is_valid_ec(x) -> bool:
    return x is not None and math.isfinite(x) and (VALID_EC_MIN <= float(x) <= VALID_EC_MAX)

def is_valid_ph(x) -> bool:
    return x is not None and math.isfinite(x) and (VALID_PH_MIN <= float(x) <= VALID_PH_MAX)

def is_valid_tp(x) -> bool:
    return x is not None and math.isfinite(x) and (VALID_TP_MIN <= float(x) <= VALID_TP_MAX)


# ===============================
# SQLite helpers
# ===============================
def ensure_db_schema(db_path: str):
    """Ensure target table/index exist (idempotent)."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS "{DB_TABLE}" (
                "Date" TEXT,
                "EC" REAL,
                "pH" REAL,
                "Solution_Temperature" REAL
            );
        """)
        conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_dist2_ecph_date" ON "{DB_TABLE}"("Date");')
        conn.commit()
    finally:
        conn.close()

def insert_row(db_path: str, date_str: str, ec, ph, tp):
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(
            f'INSERT INTO "{DB_TABLE}" ("Date","EC","pH","Solution_Temperature") VALUES (?,?,?,?);',
            (date_str, ec, ph, tp)
        )
        conn.commit()
    finally:
        conn.close()


# ===============================
# Read one request with lock + retry
# ===============================
def request_once_with_lock_and_retry():
    """
    Returns (ec, ph, tp, err_or_none)
    """
    lockf = open(SERIAL_LOCK_PATH, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX)

        last_err = None

        for _ in range(RETRY_ATTEMPTS):
            try:
                with serial.Serial(
                    PORT, baudrate=BAUD,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.1
                ) as ser:
                    time.sleep(0.15)
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()

                    ser.write(REQ.encode("ascii", errors="ignore"))
                    ser.flush()

                    raw = read_burst(ser, total_timeout=TOTAL_TIMEOUT_SEC, idle_gap=IDLE_GAP_SEC)
                    if not raw:
                        last_err = "no_data"
                        time.sleep(RETRY_DELAY_SEC)
                        continue

                    text = safe_decode(raw)

                    json_part = extract_json_block(text)
                    if not json_part:
                        last_err = "no_json_block"
                        time.sleep(RETRY_DELAY_SEC)
                        continue

                    try:
                        data = json.loads(json_part)
                    except Exception as e:
                        last_err = f"json_load_error: {e}"
                        time.sleep(RETRY_DELAY_SEC)
                        continue

                    ph = get_value_by_id(data, ID_PH)
                    tp = get_value_by_id(data, ID_TEMP)
                    ec = get_value_by_id(data, ID_EC)

                    return ec, ph, tp, None

            except (SerialException, OSError) as e:
                last_err = f"serial_error: {e}"
                time.sleep(RETRY_DELAY_SEC)
            except Exception as e:
                last_err = f"unknown_error: {e}"
                time.sleep(RETRY_DELAY_SEC)

        return None, None, None, last_err

    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        except Exception:
            pass
        lockf.close()


# ===============================
# Main loop
# ===============================
def main():
    ensure_db_schema(DB_PATH)

    latest_ec = None
    latest_ph = None
    latest_tp = None
    latest_err = None

    last_saved_slot = None  # prevent duplicate insert per boundary slot

    # Optional: started message (still one-line JSON)
    print(json.dumps({
        "type": "started",
        "db": DB_PATH,
        "table": DB_TABLE,
        "poll_sec": POLL_SEC,
        "db_every_min": DB_EVERY_MIN
    }, ensure_ascii=False), flush=True)

    while True:
        sleep_to_next_boundary(POLL_SEC)

        ec, ph, tp, err = request_once_with_lock_and_retry()

        if err is None:
            if is_valid_ec(ec):
                latest_ec = round(float(ec), 2)
            if is_valid_ph(ph):
                latest_ph = round(float(ph), 2)
            if is_valid_tp(tp):
                latest_tp = round(float(tp), 2)
            latest_err = None
        else:
            latest_err = err

        now = datetime.datetime.now()
        mkey = minute_key(now)

        # Base output (ALWAYS one line JSON)
        out = {
            "type": "report",
            "date": mkey,
            "EC": latest_ec,
            "pH": latest_ph,
            "Solution_Temperature": latest_tp,
            "errors": {
                "sensor": latest_err,
                "db": None
            },
            "save": {
                "rule": f"minute%{DB_EVERY_MIN}==0",
                "should": False,
                "did": False,
                "slot": None
            }
        }

        # DB save at boundary minute (00/15/30/45) once per slot
        if now.minute % DB_EVERY_MIN == 0:
            out["save"]["should"] = True

            slot_min = (now.minute // DB_EVERY_MIN) * DB_EVERY_MIN
            slot_dt = now.replace(minute=slot_min, second=0, microsecond=0)
            slot_key = slot_dt.strftime("%Y-%m-%d %H:%M")
            out["save"]["slot"] = slot_key

            if last_saved_slot != slot_key:
                if latest_ec is None or latest_ph is None or latest_tp is None:
                    out["errors"]["db"] = "skip_save: latest values are None"
                else:
                    try:
                        insert_row(DB_PATH, slot_key, latest_ec, latest_ph, latest_tp)
                        last_saved_slot = slot_key
                        out["save"]["did"] = True
                    except Exception as e:
                        out["errors"]["db"] = f"db_write_failed: {e}"

        print(json.dumps(out, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
