
# -*- coding: utf-8 -*-
import os
import json
import time
import csv
import datetime
import serial
import minimalmodbus
import fcntl
import pause

# ===============================
# Global lock (optional)
# ===============================
# This lock prevents concurrent access if multiple scripts might run.
# lock = open("/tmp/rs485_bus.lock", "w")
# fcntl.flock(lock, fcntl.LOCK_EX)
# pause.minutes(1)  # Simulate some delay for lock testing
# ===============================
# Paths / Settings
# ===============================
CSV_PATH = "Temp_humi_log.csv"

# Temp/Humi (Modbus RTU)
TEMP_HUMI_PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0"
TEMP_HUMI_SLAVE_ID = 2
TEMP_HUMI_REG_START = 0xC8   # temperature, humidity
TEMP_HUMI_REG_COUNT = 2
TEMP_HUMI_FC = 4             # input registers

# CO2 (ASCII serial)
CO2_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
CO2_BAUD = 115200
CO2_REQ  = "node000000|SensorReq|0905"

# ===============================
# Temp/Humi functions
# ===============================
def read_temp_humi():
    # English comment: Create instrument per run to avoid port-holding issues in Node-RED.
    dev = minimalmodbus.Instrument(TEMP_HUMI_PORT, TEMP_HUMI_SLAVE_ID, mode="rtu")
    dev.serial.baudrate = 9600
    dev.serial.bytesize = 8
    dev.serial.parity   = serial.PARITY_NONE
    dev.serial.stopbits = 2
    dev.serial.timeout  = 1

    regs = dev.read_registers(TEMP_HUMI_REG_START, TEMP_HUMI_REG_COUNT, functioncode=TEMP_HUMI_FC)
    temp = float(regs[0]) / 10.0
    humi = float(regs[1]) / 10.0
    return temp, humi

# ===============================
# CO2 functions
# ===============================
def read_one_response(ser, timeout=1.5):
    """Read until no more bytes arrive for a short idle gap (no newline protocol)."""
    ser.timeout = 0.2
    buf = bytearray()
    t0 = time.time()
    last_rx = time.time()

    while time.time() - t0 < timeout:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            last_rx = time.time()
        else:
            if buf and (time.time() - last_rx) > 0.2:
                break
    return bytes(buf)

def extract_json_block(text: str):
    """Extract {...} part from '|SensorRes|{...}|XXXX'."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end + 1]

def parse_co2_value(text: str):
    """Return CO2 value (id=6) as int if possible, else None."""
    json_part = extract_json_block(text)
    if not json_part:
        return None

    try:
        data = json.loads(json_part)
    except:
        return None

    for s in data.get("sensors", []):
        if s.get("id") == 6:
            v = str(s.get("value", "")).strip()
            try:
                return int(v)
            except:
                try:
                    return float(v)
                except:
                    return None
    return None

def read_co2():
    with serial.Serial(CO2_PORT, CO2_BAUD, bytesize=8, parity="N", stopbits=1, timeout=0.2) as ser:
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        ser.write(CO2_REQ.encode("ascii"))
        ser.flush()

        raw = read_one_response(ser, timeout=2.0)

    text = raw.replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()
    return parse_co2_value(text)

# ===============================
# CSV logging
# ===============================
def write_csv_row(date_str, temperature, humidity, co2):
    # English comment: Write header only when file is new/empty.
    new_file = (not os.path.exists(CSV_PATH)) or (os.stat(CSV_PATH).st_size == 0)

    def to_cell(x):
        return "" if x is None else x

    with open(CSV_PATH, mode="a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "temperature", "humidity", "co2"])
        w.writerow([date_str, to_cell(temperature), to_cell(humidity), to_cell(co2)])

# ===============================
# Main
# ===============================
if __name__ == "__main__":
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    temperature = None
    humidity = None
    co2 = None

    # Temp/Humi
    try:
        temperature, humidity = read_temp_humi()
    except:
        pass

    # CO2
    try:
        # pause.minutes(1)  # Simulate some delay for lock testing
        co2 = read_co2()
    except:
        pass

    # Save one-row CSV (date, temperature, humidity, co2)
    write_csv_row(date_str, temperature, humidity, co2)

    # Node-RED output JSON
    out = {
        "date": date_str,
        "temperature": temperature,
        "humidity": humidity,
        "co2": co2
    }
    print(json.dumps(out, ensure_ascii=False), flush=True)