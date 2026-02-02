# -*- coding: utf-8 -*-
import os
import json
import time
import datetime
import sqlite3
import fcntl

import minimalmodbus
import serial

# ===============================
# Fixed settings
# ===============================
EC_PH_PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0"
SLAVE_ID = 1

DB_PATH = "/home/cja/Work/cja-skyfarms-project/data/data.db"
DB_TABLE = "Dist_1_EC_pH_log"

BUS_LOCK_PATH = "/tmp/rs485_bus.lock"

PRINT_EVERY_SEC = 10
SAVE_EVERY_MIN = 20   # 00/20/40

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
    """Floor dt to the slot boundary minute (e.g., 20-min slots)."""
    slot_min = (dt.minute // step_min) * step_min
    slot_dt = dt.replace(minute=slot_min, second=0, microsecond=0)
    return slot_dt.strftime("%Y-%m-%d %H:%M")

# ===============================
# Modbus init
# ===============================
dev = minimalmodbus.Instrument(EC_PH_PORT, SLAVE_ID, mode="rtu")
dev.serial.baudrate = 9600
dev.serial.bytesize = 8
dev.serial.parity   = serial.PARITY_NONE
dev.serial.stopbits = 1
dev.serial.timeout  = 1
dev.clear_buffers_before_each_transaction = True

# ===============================
# SQLite helpers
# ===============================
def insert_dist1(db_path: str, table: str, date_str: str, ec, ph, temp):
    """Insert one row into SQLite."""
    conn = sqlite3.connect(db_path, timeout=5.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(
            f'INSERT INTO "{table}" ("Date","EC","pH","Solution_Temperature") VALUES (?,?,?,?);',
            (date_str, ec, ph, temp)
        )
        conn.commit()
    finally:
        conn.close()

# ===============================
# Read once
# ===============================
def read_once():
    """
    Read all three once.
    - pH: decimals=2
    - EC: /10
    - Solution_Temperature: *10 (as your current spec)
    """
    ph = dev.read_register(0x00, 2, functioncode=3)
    ec = dev.read_register(0x01, 2, functioncode=3) / 10.0
    tp = dev.read_register(0x02, 2, functioncode=3) * 10.0
    return round(ec, 2), round(ph, 2), round(tp, 2)

def read_with_lock():
    """Read Modbus values with a filesystem lock to avoid collisions."""
    lockf = open(BUS_LOCK_PATH, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        return read_once(), None
    except Exception as e:
        return (None, None, None), str(e)
    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        except Exception:
            pass
        lockf.close()

# ===============================
# Main (continuous)
# ===============================
def main():
    latest_ec = None
    latest_ph = None
    latest_tp = None
    latest_err = None

    last_saved_slot = None  # "YYYY-MM-DD HH:MM" at 00/20/40

    # Optional started message
    print(json.dumps({
        "type": "started",
        "port": EC_PH_PORT,
        "slave": SLAVE_ID,
        "poll_sec": PRINT_EVERY_SEC,
        "db_every_min": SAVE_EVERY_MIN,
        "table": DB_TABLE
    }, ensure_ascii=False), flush=True)

    while True:
        # 1) Read every 10 seconds (no drift)
        sleep_to_next_boundary(PRINT_EVERY_SEC)

        (ec, ph, tp), err = read_with_lock()

        if err is None and ec is not None and ph is not None and tp is not None:
            latest_ec, latest_ph, latest_tp = ec, ph, tp
            latest_err = None
        else:
            latest_err = err

        now = datetime.datetime.now()
        mkey = minute_key(now)

        out = {
            "type": "report",
            "date": mkey,
            "EC": latest_ec,
            "pH": latest_ph,
            "Solution_Temperature": latest_tp,
            "errors": {"sensor": latest_err, "db": None},
            "save": {
                "rule": f"minute%{SAVE_EVERY_MIN}==0",
                "should": False,
                "did": False,
                "slot": None
            }
        }

        # 2) DB save every 20 minutes at boundary minute (00/20/40), once per slot
        if now.minute % SAVE_EVERY_MIN == 0:
            out["save"]["should"] = True
            skey = slot_key_for(now, SAVE_EVERY_MIN)   # floor to boundary
            out["save"]["slot"] = skey

            if last_saved_slot != skey:
                if latest_ec is None or latest_ph is None or latest_tp is None:
                    out["errors"]["db"] = "skip_save: latest values are None"
                else:
                    try:
                        insert_dist1(DB_PATH, DB_TABLE, skey, latest_ec, latest_ph, latest_tp)
                        last_saved_slot = skey
                        out["save"]["did"] = True
                    except Exception as e:
                        out["errors"]["db"] = f"db_write_failed: {e}"

        print(json.dumps(out, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
