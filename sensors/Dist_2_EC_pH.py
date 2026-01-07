# -*- coding: utf-8 -*-
import os
import csv
import json
import time
import datetime
import serial

# ===============================
# Settings
# ===============================

PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
BAUD = 115200
REQ  = "node000300|SensorReq|8985"

# Assumed mapping (adjust if needed)
ID_PH   = 16
ID_TEMP = 29
ID_EC   = 30

# Sampling
SAMPLES = 20
SAMPLE_INTERVAL_SEC = 0.2   # gap between requests (tune if needed)

# Serial read behavior (device has no newline terminator)
TOTAL_TIMEOUT_SEC = 3.0
IDLE_GAP_SEC = 0.2

# CSV log
CSV_PATH = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_2_EC_pH_log.csv"


# ===============================
# Helpers
# ===============================

def now_str(sec=False) -> str:
    """Return timestamp string."""
    fmt = "%Y-%m-%d %H:%M:%S" if sec else "%Y-%m-%d %H:%M"
    return datetime.datetime.now().strftime(fmt)

def ensure_csv_header(path: str):
    """Create directory and write header if file is missing/empty."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if (not os.path.exists(path)) or (os.path.getsize(path) == 0):
        with open(path, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "EC", "pH", "Solution_Temperature"])

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

def extract_json_block(text: str):
    """Extract {...} from '|SensorRes|{...}|XXXX'."""
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    return text[s:e+1]

def get_value_by_id(data: dict, target_id: int):
    """Find sensor value by sensor id and return float if possible."""
    for s in data.get("sensors", []):
        if s.get("id") == target_id:
            v = str(s.get("value", "")).strip()
            try:
                return float(v)
            except:
                return None
    return None

def request_once(ser):
    """Send one request and parse EC/pH/temp from response."""
    # IMPORTANT: send request WITHOUT newline/CRLF
    ser.write(REQ.encode("ascii", errors="ignore"))
    ser.flush()

    raw = read_burst(ser, total_timeout=TOTAL_TIMEOUT_SEC, idle_gap=IDLE_GAP_SEC)
    text = raw.replace(b"\x00", b"").decode("utf-8", errors="replace").strip()

    j = extract_json_block(text)
    if not j:
        return None, None, None, f"no_json_block: {text}"

    try:
        data = json.loads(j)
    except Exception as e:
        return None, None, None, f"json_load_error: {e}"

    ph = get_value_by_id(data, ID_PH)
    temp = get_value_by_id(data, ID_TEMP)
    ec = get_value_by_id(data, ID_EC)

    if (ph is None) or (temp is None) or (ec is None):
        return None, None, None, f"value_missing: ph={ph}, temp={temp}, ec={ec}"

    return ec, ph, temp, None


# def main():
#     ensure_csv_header(CSV_PATH)

#     ec_list, ph_list, temp_list = [], [], []

#     try:
#         with serial.Serial(
#             PORT, baudrate=BAUD,
#             bytesize=serial.EIGHTBITS,
#             parity=serial.PARITY_NONE,
#             stopbits=serial.STOPBITS_ONE,
#             timeout=0.1
#         ) as ser:
#             # Clear buffers once at the start
#             time.sleep(0.2)
#             ser.reset_input_buffer()
#             ser.reset_output_buffer()

#             for i in range(SAMPLES):
#                 ec, ph, temp, err = request_once(ser)
#                 if err:
#                     # If one sample fails, just skip it (robust averaging)
#                     # You can change this behavior to "fail fast" if you want.
#                     time.sleep(SAMPLE_INTERVAL_SEC)
#                     continue

#                 ec_list.append(ec)
#                 ph_list.append(ph)
#                 temp_list.append(temp)

#                 time.sleep(SAMPLE_INTERVAL_SEC)

#     except Exception as e:
#         print(json.dumps({"error": str(e)}, ensure_ascii=False), flush=True)
#         return

#     if not ec_list:
#         print(json.dumps({"error": "no_valid_samples"}, ensure_ascii=False), flush=True)
#         return

#     avg_ec = round(sum(ec_list) / len(ec_list), 2)
#     avg_ph = round(sum(ph_list) / len(ph_list), 2)
#     avg_temp = round(sum(temp_list) / len(temp_list), 2)

#     date_str = now_str(sec=False)

#     # Append to CSV
#     try:
#         with open(CSV_PATH, mode="a", newline="") as f:
#             writer = csv.writer(f)
#             writer.writerow([date_str, avg_ec, avg_ph, avg_temp])
#             f.flush()
#             os.fsync(f.fileno())
#     except Exception as e:
#         print(json.dumps({"error": f"csv_write_failed: {e}"}, ensure_ascii=False), flush=True)
#         return

#     # Node-RED friendly JSON (matches your Change nodes)
#     print(json.dumps({
#         "date": date_str,
#         "EC": avg_ec,
#         "pH": avg_ph,
#         "Solution_Temperature": avg_temp
#     }, ensure_ascii=False), flush=True)

def main():
    ensure_csv_header(CSV_PATH)

    ec_list, ph_list, temp_list = [], [], []
    err_counts = {}
    last_err = None

    try:
        with serial.Serial(
            PORT, baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1
        ) as ser:
            time.sleep(0.2)
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            for _ in range(SAMPLES):
                ec, ph, temp, err = request_once(ser)
                if err:
                    last_err = err
                    key = err.split(":")[0]  # e.g., "no_json_block", "json_load_error", "value_missing"
                    err_counts[key] = err_counts.get(key, 0) + 1
                    time.sleep(SAMPLE_INTERVAL_SEC)
                    continue

                ec_list.append(ec)
                ph_list.append(ph)
                temp_list.append(temp)
                time.sleep(SAMPLE_INTERVAL_SEC)

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), flush=True)
        return

    if not ec_list:
        print(json.dumps({
            "error": "no_valid_samples",
            "err_counts": err_counts,
            "last_err": (last_err[:400] if isinstance(last_err, str) else last_err)
        }, ensure_ascii=False), flush=True)
        return

    avg_ec = round(sum(ec_list) / len(ec_list), 2)
    avg_ph = round(sum(ph_list) / len(ph_list), 2)
    avg_temp = round(sum(temp_list) / len(temp_list), 2)

    date_str = now_str(sec=False)

    try:
        with open(CSV_PATH, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([date_str, avg_ec, avg_ph, avg_temp])
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        print(json.dumps({"error": f"csv_write_failed: {e}"}, ensure_ascii=False), flush=True)
        return

    print(json.dumps({
        "date": date_str,
        "EC": avg_ec,
        "pH": avg_ph,
        "Solution_Temperature": avg_temp,
        "valid_samples": len(ec_list)
    }, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
