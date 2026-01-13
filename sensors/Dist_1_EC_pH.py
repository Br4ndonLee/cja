# -*- coding: utf-8 -*-
import os
import csv
import json
import datetime
import minimalmodbus
import serial

# ===============================
# Fixed settings
# ===============================
EC_PH_PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0"
SLAVE_ID = 1

CSV_PATH = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_1_EC_pH_log.csv"

PRINT_EVERY_MIN = 3
SAVE_EVERY_MIN = 20

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
# CSV helpers
# ===============================
def ensure_csv_ready(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if (not os.path.exists(path)) or (os.path.getsize(path) == 0):
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Date", "EC", "pH", "Solution_Temperature"])

def append_csv_row(path: str, date_str: str, ec, ph, temp):
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([date_str, ec, ph, temp])
        f.flush()
        os.fsync(f.fileno())

# ===============================
# Read once
# ===============================
def read_once():
    """
    Read all three once.
    - EC: /10
    - pH: as-is
    - Solution_Temperature: *10 (as you specified)
    """
    ph = dev.read_register(0x00, 2, functioncode=3)
    ec = dev.read_register(0x01, 2, functioncode=3) / 10.0
    tp = dev.read_register(0x02, 2, functioncode=3) * 10.0
    return round(ec, 2), round(ph, 2), round(tp, 2)

# ===============================
# Main (one-shot)
# ===============================
def main():
    ensure_csv_ready(CSV_PATH)

    now = datetime.datetime.now()
    minute_key = now.strftime("%Y-%m-%d %H:%M")

    # 1) Try read
    try:
        ec, ph, tp = read_once()
    except Exception:
        # IMPORTANT: don't print non-JSON or partial JSON; Node-RED JSON node can break.
        return

    # 2) JSON print only at minute%3==0
    if now.minute % PRINT_EVERY_MIN == 0:
        print(json.dumps({
            "date": minute_key,
            "EC": ec,
            "pH": ph,
            "Solution_Temperature": tp
        }, ensure_ascii=False), flush=True)

    # 3) CSV save only at minute%20==0
    if now.minute % SAVE_EVERY_MIN == 0:
        try:
            append_csv_row(CSV_PATH, minute_key, ec, ph, tp)
        except Exception:
            # keep silent to avoid breaking JSON parsing in Node-RED
            pass

if __name__ == "__main__":
    main()