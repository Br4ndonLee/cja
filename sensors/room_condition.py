# -*- coding: utf-8 -*-
import os
import json
import time
import csv
import datetime
import serial
import fcntl
from serial.serialutil import SerialException

# ===============================
# Settings
# ===============================
PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
BAUD = 115200
REQ  = "node000000|SensorReq|0905"

CSV_PATH = "/home/cja/Work/cja-skyfarms-project/sensors/Temp_humi_log.csv"

ID_TEMPERATURE = 1
ID_HUMIDITY    = 2
ID_CO2         = 6

SERIAL_LOCK_PATH = "/tmp/usb_1a86_serial.lock"

READ_TIMEOUT_SEC = 2.5
IDLE_GAP_SEC = 0.2

RETRY_ATTEMPTS = 3
RETRY_DELAY_SEC = 0.25


def read_one_response(ser, timeout=1.5, idle_gap=0.2):
    """Read until no more bytes arrive for a short idle gap (no newline protocol)."""
    ser.timeout = idle_gap
    buf = bytearray()
    t0 = time.time()
    last_rx = time.time()

    while time.time() - t0 < timeout:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            last_rx = time.time()
        else:
            if buf and (time.time() - last_rx) > idle_gap:
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
            except:
                return None
    return None


def ensure_csv_header(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if (not os.path.exists(path)) or (os.path.getsize(path) == 0):
        with open(path, mode="a", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "temperature", "humidity", "co2"])


def append_csv_row(path: str, date_str: str, temperature, humidity, co2):
    def cell(x):
        return "" if x is None else x

    with open(path, mode="a", newline="") as f:
        w = csv.writer(f)
        w.writerow([date_str, cell(temperature), cell(humidity), cell(co2)])
        f.flush()
        os.fsync(f.fileno())


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

    data = json.loads(json_part)

    temperature = get_value_by_id(data, ID_TEMPERATURE)
    humidity = get_value_by_id(data, ID_HUMIDITY)
    co2_val = get_value_by_id(data, ID_CO2)

    if co2_val is None:
        co2 = None
    else:
        try:
            co2 = int(co2_val)
        except:
            co2 = co2_val

    if temperature is None or humidity is None or co2 is None:
        return temperature, humidity, co2, "value_missing"

    return temperature, humidity, co2, None


def read_sensor_with_lock_and_retry():
    """Prevent concurrent access + retry a few times for stability under Node-RED."""
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
            except (SerialException, OSError, json.JSONDecodeError, ValueError) as e:
                last_err = str(e)

            time.sleep(RETRY_DELAY_SEC)

        return last_vals[0], last_vals[1], last_vals[2], last_err

    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        except:
            pass
        lockf.close()


if __name__ == "__main__":
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    temperature, humidity, co2, err = read_sensor_with_lock_and_retry()

    ensure_csv_header(CSV_PATH)
    append_csv_row(CSV_PATH, date_str, temperature, humidity, co2)

    print(json.dumps({
        "date": date_str,
        "temperature": temperature,
        "humidity": humidity,
        "co2": co2,
        "errors": {"sensor": err}
    }, ensure_ascii=False), flush=True)
