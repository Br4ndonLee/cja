# -*- coding: utf-8 -*-
import os
import time
import csv
import json
import datetime
import minimalmodbus
import serial

# === Modbus device settings ===
dev = minimalmodbus.Instrument("/dev/ttyACM1", 1, mode='rtu')  # Adjust port/slave ID to your setup
dev.serial.baudrate = 9600
dev.serial.bytesize = 8
dev.serial.parity   = serial.PARITY_NONE
dev.serial.stopbits = 1
dev.serial.timeout  = 1

# === CSV file path (use absolute path for safety) ===
csv_file_path = "/home/cja/Work/cja-skyfarms-project/sensors/EC_pH_log.csv"

# === Sampling/averaging settings ===
DURATION_SEC = 5   # 5 seconds
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

def main():

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
    avg_ph = round(sum(ph_list) / num_ph, 2)
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"Avg EC: {avg_ec} dS/m, Avg pH: {avg_ph}")
   

if __name__ == "__main__":
    main()
