# -*- coding: utf-8 -*-
import os
import time
import csv
import json
import datetime
import minimalmodbus
import serial

# ===============================
# Modbus device settings
# ===============================
EC_PH_PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0"

dev = minimalmodbus.Instrument(EC_PH_PORT, 1, mode="rtu")
dev.serial.baudrate = 9600
dev.serial.bytesize = 8
dev.serial.parity   = serial.PARITY_NONE
dev.serial.stopbits = 2
dev.serial.timeout  = 1
dev.clear_buffers_before_each_transaction = True

# ===============================
# CSV settings
# ===============================
CSV_PATH = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_1_EC_pH_log.csv"

def ensure_csv_ready(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if (not os.path.exists(path)) or (os.path.getsize(path) == 0):
        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "EC", "pH", "Solution_Temperature"])

# ===============================
# Sensor read
# ===============================
def safe_read_once():
    try:
        ph = dev.read_register(0x00, 2, functioncode=3)
        ec = dev.read_register(0x01, 2, functioncode=3) / 10.0
        solution_temp = dev.read_register(0x02, 2, functioncode=3) * 10.0
        return round(ec, 2), round(ph, 2), round(solution_temp, 2)
    except Exception:
        return None, None, None

def sleep_to_next_10s():
    """
    Sleep until the next wall-clock 10-second boundary.
    e.g. HH:MM:00, :10, :20, :30, :40, :50
    """
    now = time.time()
    next_t = (int(now) // 10 + 1) * 10
    time.sleep(max(0, next_t - now))

# ===============================
# Main loop
# ===============================
def main():
    ensure_csv_ready(CSV_PATH)

    latest_ec = None
    latest_ph = None
    latest_temp = None

    last_saved_minute = None

    while True:
        # --- align to next 10-second boundary (NO DRIFT) ---
        sleep_to_next_10s()

        # --- read sensor ---
        ec, ph, temp = safe_read_once()
        if ec is not None and ph is not None:
            latest_ec = ec
            latest_ph = ph
            latest_temp = temp

        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d %H:%M")

        # --- every 20 minutes, save ONLY ONCE ---
        if (
            now.minute % 20 == 0
            and latest_ec is not None
            and last_saved_minute != date_str
        ):
            try:
                with open(CSV_PATH, "a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow([date_str, latest_ec, latest_ph, latest_temp])
                    f.flush()
                    os.fsync(f.fileno())

                print(json.dumps({
                    "date": date_str,
                    "EC": latest_ec,
                    "pH": latest_ph,
                    "Solution_Temperature": latest_temp
                }, ensure_ascii=False), flush=True)

                last_saved_minute = date_str

            except Exception as e:
                print(json.dumps({
                    "error": f"CSV write failed: {e}"
                }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()