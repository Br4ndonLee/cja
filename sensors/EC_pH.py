# -*- coding: utf-8 -*-
import os
import time
import csv
import json
import datetime
import minimalmodbus
import serial
import pause

# === Modbus device settings ===
dev = minimalmodbus.Instrument("/dev/ttyACM1", 1, mode='rtu')  # Adjust port/slave ID to your setup
dev.serial.baudrate = 9600
dev.serial.bytesize = 8
dev.serial.parity   = serial.PARITY_NONE
dev.serial.stopbits = 1
dev.serial.timeout  = 1

now = datetime.datetime.now()

# === CSV file path (use absolute path for safety) ===
csv_file_path = "/home/cja/Work/cja-skyfarms-project/sensors/EC_pH_log.csv"

# === Sampling/averaging settings ===
DURATION_SEC = 20       # 20 seconds
INTERVAL_SEC = 1         # Every 1 second

def safe_read_once():
    """Read EC, pH once (return None if failed).
    minimalmodbus returns values already scaled according to decimal setting."""
    try:
        ph = dev.read_register(0x00, 2, functioncode=3)  # pH register 0x00
        # EC has to change dS/m
        ec = (dev.read_register(0x01, 2, functioncode=3)/10)  # EC register 0x01
        return float(ec), float(ph)
    except Exception:
        return None, None

def ensure_csv_ready(path):
    """Create CSV directory and header if missing"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    need_header = (not os.path.exists(path)) or (os.path.getsize(path) == 0)
    if need_header:
        with open(path, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "EC", "pH"])

def main():
    # start = time.monotonic()
    ensure_csv_ready(csv_file_path)

    ec_list = []
    ph_list = []
    start = time.monotonic()
    next_tick = start

    while True:
        ec, ph = safe_read_once()
        if ec is not None and ph is not None:
            ec_list.append(ec)
            ph_list.append(ph)

        if time.monotonic() - start >= DURATION_SEC:
            break

        next_tick += INTERVAL_SEC
        time.sleep(max(0, next_tick - time.monotonic()))
    num_ec = float(len(ec_list))
    num_ph = float(len(ph_list))
    # print(ec_list, ph_list)
    avg_ec = round(sum(ec_list) / num_ec, 2)
    avg_ph = round(0.9926*(sum(ph_list) / num_ph)-0.2488, 2)
    
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    try:
         # if now.minute % 20 == 0:
         #    with open(csv_file_path, mode="a", newline="") as f:
         #        writer = csv.writer(f)
         #        writer.writerow([date_str, avg_ec, avg_ph])
         #        f.flush()
         #        os.fsync(f.fileno())
         #        pause.minutes (1)
        with open(csv_file_path, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([date_str, avg_ec, avg_ph])
            f.flush()
            os.fsync(f.fileno())
            # end = time.monotonic()
    except Exception as e:
        print(json.dumps({"error": f"CSV write failed: {e}"}), flush=True)
        return

    print(json.dumps({"date": date_str, "EC": avg_ec, "pH": avg_ph}, ensure_ascii=False), flush=True)
    # elapsed = end - start
    # print(f"Elapsed time: {elapsed:.2f} seconds", flush=True)
    # print(f"Avg EC: {avg_ec} dS/m, Avg pH: {avg_ph}")

if __name__ == "__main__":
    main()
