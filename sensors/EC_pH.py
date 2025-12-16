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
# dev = minimalmodbus.Instrument("/dev/ttyACM1", 1, mode='rtu')  # Adjust port/slave ID to your setup
# dev = minimalmodbus.Instrument("/dev/ttyUSB1", 1, mode='rtu')  # Adjust port/slave ID to your setup

# EC/pH sensor connected via USB serial port
EC_PH_PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0"  # EC/pH¸¸ ²ÈÈù Æ÷Æ®·Î

dev = minimalmodbus.Instrument(EC_PH_PORT, 1, mode='rtu')
dev.serial.baudrate = 9600
dev.serial.bytesize = 8
dev.serial.parity   = serial.PARITY_NONE
dev.serial.stopbits = 2
dev.serial.timeout  = 1

dev.clear_buffers_before_each_transaction = True

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
        solution_temp = (dev.read_register(0x02, 2, functioncode=3))*10  # Solution temperature register 0x02
        return float(ec), float(ph), float(solution_temp)
    except Exception:
        return None, None, None

def ensure_csv_ready(path):
    """Create CSV directory and header if missing"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    need_header = (not os.path.exists(path)) or (os.path.getsize(path) == 0)
    if need_header:
        with open(path, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "EC", "pH", "Solution_Temperature"])
def main():
    # start = time.monotonic()
    ensure_csv_ready(csv_file_path)

    ec_list = []
    ph_list = []
    solution_temp_list = []
    start = time.monotonic()
    next_tick = start

    while True:
        ec, ph, solution_temp = safe_read_once()
        if ec is not None and ph is not None:
            ec_list.append(ec)
            ph_list.append(ph)
            solution_temp_list.append(solution_temp)

        if time.monotonic() - start >= DURATION_SEC:
            break

        next_tick += INTERVAL_SEC
        time.sleep(max(0, next_tick - time.monotonic()))
    num_ec = float(len(ec_list))
    num_ph = float(len(ph_list))
    num_solution_temp = float(len(solution_temp_list))
    # print(ec_list, ph_list)
    avg_ec = round(sum(ec_list) / num_ec, 2)
    avg_ph = round(0.9926*(sum(ph_list) / num_ph)-0.2488, 2)
    avg_solution_temp = round(sum(solution_temp_list) / num_solution_temp, 2)
    
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
            writer.writerow([date_str, avg_ec, avg_ph, avg_solution_temp])
            f.flush()
            os.fsync(f.fileno())
            # end = time.monotonic()
    except Exception as e:
        print(json.dumps({"error": f"CSV write failed: {e}"}), flush=True)
        return

    print(json.dumps({"date": date_str, "EC": avg_ec, "pH": avg_ph, "Solution_Temperature": avg_solution_temp}, ensure_ascii=False), flush=True)
    # elapsed = end - start
    # print(f"Elapsed time: {elapsed:.2f} seconds", flush=True)
    # print(f"Avg EC: {avg_ec} dS/m, Avg pH: {avg_ph}")

if __name__ == "__main__":
    main()
