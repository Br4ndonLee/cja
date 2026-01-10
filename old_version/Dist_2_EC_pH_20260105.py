# # -*- coding: utf-8 -*-
# import os
# import csv
# import json
# import time
# import datetime
# import serial
# import fcntl
# import re
# from serial.serialutil import SerialException

# # ===============================
# # Settings
# # ===============================
# PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
# BAUD = 115200
# REQ  = "node000300|SensorReq|8985"

# ID_PH   = 16
# ID_TEMP = 29
# ID_EC   = 30

# CSV_PATH = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_2_EC_pH_log.csv"

# TOTAL_TIMEOUT_SEC = 3.0
# IDLE_GAP_SEC = 0.2

# SERIAL_LOCK_PATH = "/tmp/usb_1a86_serial.lock"
# RETRY_ATTEMPTS = 3
# RETRY_DELAY_SEC = 0.25


# # ===============================
# # Timing (no drift)
# # ===============================
# def sleep_to_next_10s():
#     """Sleep until the next wall-clock 10-second boundary (no drift)."""
#     now = time.time()
#     next_t = (int(now) // 10 + 1) * 10
#     time.sleep(max(0, next_t - now))


# # ===============================
# # CSV helpers
# # ===============================
# def ensure_csv_header(path: str):
#     """Create directory and write header if file is missing/empty."""
#     os.makedirs(os.path.dirname(path), exist_ok=True)
#     if (not os.path.exists(path)) or (os.path.getsize(path) == 0):
#         with open(path, mode="a", newline="") as f:
#             w = csv.writer(f)
#             w.writerow(["Date", "EC", "pH", "Solution_Temperature", "error"])


# def append_csv_row(path: str, date_str: str, ec, ph, temp, err):
#     """Append one row (allow blanks) and fsync for safety."""
#     def cell(x):
#         return "" if x is None else x

#     with open(path, mode="a", newline="") as f:
#         w = csv.writer(f)
#         w.writerow([date_str, cell(ec), cell(ph), cell(temp), cell(err)])
#         f.flush()
#         os.fsync(f.fileno())


# # ===============================
# # Serial helpers
# # ===============================
# def read_burst(ser, total_timeout=3.0, idle_gap=0.2) -> bytes:
#     """Read bytes until idle gap after some data (no newline protocol)."""
#     ser.timeout = 0.1
#     buf = bytearray()
#     t0 = time.time()
#     last_rx = None

#     while time.time() - t0 < total_timeout:
#         chunk = ser.read(256)
#         if chunk:
#             buf += chunk
#             last_rx = time.time()
#         else:
#             if buf and last_rx and (time.time() - last_rx) > idle_gap:
#                 break
#     return bytes(buf)


# def safe_decode(raw: bytes) -> str:
#     """Decode even if bytes are broken; strip control chars."""
#     raw = raw.replace(b"\x00", b"")
#     text = raw.decode("utf-8", errors="replace")
#     text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
#     return text.strip()


# def parse_values_very_robust(text: str):
#     """
#     Extract id/value pairs from possibly corrupted payload.
#     We rely on the fact that 'id' and numeric 'value' often survive.
#     """
#     pat = re.compile(
#         r'id[^0-9]{0,8}(\d{1,4})[^0-9]{0,30}value[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)',
#         re.IGNORECASE
#     )

#     found = {}
#     for m in pat.finditer(text):
#         try:
#             sid = int(m.group(1))
#             val = float(m.group(2))
#             found[sid] = val
#         except:
#             pass

#     return found.get(ID_EC), found.get(ID_PH), found.get(ID_TEMP)


# def request_once_with_lock_and_retry():
#     """
#     Lock bus -> open serial -> request once -> parse -> retry.
#     Returns (ec, ph, temp, err_string_or_None).
#     """
#     lockf = open(SERIAL_LOCK_PATH, "w")
#     try:
#         fcntl.flock(lockf, fcntl.LOCK_EX)

#         last_err = None
#         last_text = ""

#         for _ in range(RETRY_ATTEMPTS):
#             try:
#                 with serial.Serial(
#                     PORT, baudrate=BAUD,
#                     bytesize=serial.EIGHTBITS,
#                     parity=serial.PARITY_NONE,
#                     stopbits=serial.STOPBITS_ONE,
#                     timeout=0.1
#                 ) as ser:
#                     time.sleep(0.15)
#                     ser.reset_input_buffer()
#                     ser.reset_output_buffer()

#                     ser.write(REQ.encode("ascii", errors="ignore"))
#                     ser.flush()

#                     raw = read_burst(ser, total_timeout=TOTAL_TIMEOUT_SEC, idle_gap=IDLE_GAP_SEC)
#                     if not raw:
#                         last_err = "no_data"
#                         time.sleep(RETRY_DELAY_SEC)
#                         continue

#                     text = safe_decode(raw)
#                     last_text = text[:200]  # keep a short hint
#                     ec, ph, temp = parse_values_very_robust(text)

#                     if ec is None or ph is None or temp is None:
#                         last_err = f"value_missing: head={last_text}"
#                         time.sleep(RETRY_DELAY_SEC)
#                         continue

#                     return ec, ph, temp, None

#             except (SerialException, OSError) as e:
#                 last_err = f"serial_error: {e}"
#                 time.sleep(RETRY_DELAY_SEC)
#             except Exception as e:
#                 last_err = f"unknown_error: {e}"
#                 time.sleep(RETRY_DELAY_SEC)

#         return None, None, None, last_err

#     finally:
#         try:
#             fcntl.flock(lockf, fcntl.LOCK_UN)
#         except:
#             pass
#         lockf.close()


# # ===============================
# # Main loop
# # ===============================
# def main():
#     ensure_csv_header(CSV_PATH)

#     latest_ec = None
#     latest_ph = None
#     latest_temp = None
#     latest_err = None

#     last_report_minute = None

#     # Start line (so Node-RED can confirm the process is alive)
#     print(json.dumps({
#         "type": "started",
#         "port": PORT,
#         "baud": BAUD,
#         "req": REQ
#     }, ensure_ascii=False), flush=True)

#     while True:
#         # 1) Poll at fixed 10s boundaries (no drift)
#         sleep_to_next_10s()

#         ec, ph, temp, err = request_once_with_lock_and_retry()
#         if err is None:
#             # Update latest good values
#             latest_ec = round(ec, 2)
#             latest_ph = round(ph, 2)
#             latest_temp = round(temp, 2)
#             latest_err = None
#         else:
#             # Keep good values, only update error
#             latest_err = err

#         now = datetime.datetime.now()
#         minute_key = now.strftime("%Y-%m-%d %H:%M")

#         # 2) Every 20 minutes, ALWAYS report once (even if values are missing)
#         if (now.minute % 20 == 0) and (last_report_minute != minute_key):
#             # Write CSV even if values are None (so you can prove it ran)
#             try:
#                 append_csv_row(CSV_PATH, minute_key, latest_ec, latest_ph, latest_temp, latest_err)
#             except Exception as e:
#                 latest_err = f"csv_write_failed: {e}"

#             # Print one-line JSON for Node-RED debug/json node
#             print(json.dumps({
#                 "type": "report",
#                 "date": minute_key,
#                 "EC": latest_ec,
#                 "pH": latest_ph,
#                 "Solution_Temperature": latest_temp
#             }, ensure_ascii=False), flush=True)

#             last_report_minute = minute_key
#             time.sleep(60)  # avoid multiple writes in the same minute


# if __name__ == "__main__":
#     main()

# -*- coding: utf-8 -*-
import os
import csv
import json
import time
import datetime
import serial
import fcntl
import re
import sys
from collections import deque
from serial.serialutil import SerialException

# ===============================
# Settings
# ===============================
PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
BAUD = 115200
REQ  = "node000300|SensorReq|8985"

ID_PH   = 16
ID_TEMP = 29
ID_EC   = 30

CSV_PATH = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_2_EC_pH_log.csv"

TOTAL_TIMEOUT_SEC = 3.0
IDLE_GAP_SEC = 0.2

SERIAL_LOCK_PATH = "/tmp/usb_1a86_serial.lock"
RETRY_ATTEMPTS = 3
RETRY_DELAY_SEC = 0.25

# Polling / reporting
POLL_SEC = 10
REPORT_MINUTES = 2  # test: 5로 바꾸면 5분마다 보고

# Hampel
HAMPEL_WINDOW = 9          # recent N points for median/MAD
HAMPEL_K = 3.0

# Confirmation (2-of-3)
CONFIRM_N = 3
CONFIRM_M = 2

# Physical plausible ranges (tune if needed)
EC_MIN, EC_MAX = 0.0, 5.0          # dS/m typical; adjust
PH_MIN, PH_MAX = 4.0, 9.5          # plant nutrient plausible; adjust
TP_MIN, TP_MAX = 5.0, 40.0         # °C plausible; adjust

# ===============================
# Timing (no drift)
# ===============================
def sleep_to_next_boundary(step_sec: int):
    """Sleep until the next wall-clock boundary (no drift)."""
    now = time.time()
    next_t = (int(now) // step_sec + 1) * step_sec
    time.sleep(max(0, next_t - now))

# ===============================
# CSV helpers
# ===============================
def ensure_csv_header(path: str):
    """Create directory and write header if file is missing/empty."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if (not os.path.exists(path)) or (os.path.getsize(path) == 0):
        with open(path, mode="a", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Date", "EC", "pH", "Solution_Temperature"])
            f.flush()
            os.fsync(f.fileno())

def append_csv_row(path: str, date_str: str, ec, ph, temp):
    """Append one row and fsync for safety."""
    with open(path, mode="a", newline="") as f:
        w = csv.writer(f)
        w.writerow([date_str, ec, ph, temp])
        f.flush()
        os.fsync(f.fileno())

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

def parse_values_very_robust(text: str):
    """
    Extract id/value pairs from possibly corrupted payload.
    This is intentionally permissive; physical validation will protect us.
    """
    pat = re.compile(
        r'id[^0-9]{0,12}(\d{1,4})[^0-9]{0,40}value[^0-9]{0,12}([0-9]+(?:\.[0-9]+)?)',
        re.IGNORECASE
    )
    found = {}
    for m in pat.finditer(text):
        try:
            sid = int(m.group(1))
            val = float(m.group(2))
            found[sid] = val
        except:
            pass
    return found.get(ID_EC), found.get(ID_PH), found.get(ID_TEMP)

# ===============================
# Validation / Filters
# ===============================
def is_valid_physical(ec, ph, tp) -> bool:
    """Reject physically impossible values early."""
    if ec is None or ph is None or tp is None:
        return False
    if not (EC_MIN <= ec <= EC_MAX):
        return False
    if not (PH_MIN <= ph <= PH_MAX):
        return False
    if not (TP_MIN <= tp <= TP_MAX):
        return False
    return True

def hampel_is_outlier(x, window_values, k=3.0):
    """Return True if x is an outlier by Hampel test on window_values."""
    if x is None or len(window_values) < 3:
        return False
    vals = sorted(window_values)
    med = vals[len(vals)//2]
    abs_devs = sorted([abs(v - med) for v in vals])
    mad = abs_devs[len(abs_devs)//2]
    if mad == 0:
        return False
    thresh = k * 1.4826 * mad
    return abs(x - med) > thresh

def within_eps(a, b, eps):
    """Check closeness for confirmation."""
    if a is None or b is None:
        return False
    return abs(a - b) <= eps

# ===============================
# One request (lock + retry)
# ===============================
def request_once_with_lock_and_retry():
    """Lock bus -> open serial -> request once -> parse -> retry."""
    lockf = open(SERIAL_LOCK_PATH, "w")
    try:
        fcntl.flock(lockf, fcntl.LOCK_EX)

        last_err = None
        last_head = ""

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
                    last_head = text[:200]
                    ec, ph, tp = parse_values_very_robust(text)

                    if ec is None or ph is None or tp is None:
                        last_err = "value_missing"
                        time.sleep(RETRY_DELAY_SEC)
                        continue

                    return ec, ph, tp, None

            except (SerialException, OSError) as e:
                last_err = f"serial_error: {e}"
                time.sleep(RETRY_DELAY_SEC)
            except Exception as e:
                last_err = f"unknown_error: {e}"
                time.sleep(RETRY_DELAY_SEC)

        return None, None, None, f"{last_err}; head={last_head}"

    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        except:
            pass
        lockf.close()

# ===============================
# Main loop
# ===============================
def main():
    ensure_csv_header(CSV_PATH)

    # Representative (accepted) values
    rep_ec = None
    rep_ph = None
    rep_tp = None
    last_err = None

    # Rolling windows for Hampel (only accepted reps feed these)
    win_ec = deque(maxlen=HAMPEL_WINDOW)
    win_ph = deque(maxlen=HAMPEL_WINDOW)
    win_tp = deque(maxlen=HAMPEL_WINDOW)

    # Candidate buffers for confirmation
    cand_ec = deque(maxlen=CONFIRM_N)
    cand_ph = deque(maxlen=CONFIRM_N)
    cand_tp = deque(maxlen=CONFIRM_N)

    last_report_minute = None

    # Optional: stderr start log (won't break JSON node)
    print(f"[start] Dist_2 sensor loop on {PORT}, baud={BAUD}", file=sys.stderr, flush=True)

    while True:
        # 1) Poll at fixed boundary (no drift)
        sleep_to_next_boundary(POLL_SEC)

        ec, ph, tp, err = request_once_with_lock_and_retry()
        if err is not None:
            last_err = err
            continue  # keep reps, do not update
        last_err = None

        # 2) Physical validation first (critical)
        if not is_valid_physical(ec, ph, tp):
            # Reject candidate immediately; do not feed filters
            continue

        ec = round(ec, 2)
        ph = round(ph, 2)
        tp = round(tp, 2)

        # 3) Hampel check (per-channel, using accepted window)
        ec_out = hampel_is_outlier(ec, list(win_ec), HAMPEL_K)
        ph_out = hampel_is_outlier(ph, list(win_ph), HAMPEL_K)
        tp_out = hampel_is_outlier(tp, list(win_tp), HAMPEL_K)

        if ec_out or ph_out or tp_out:
            # 4) Confirmation path: require 2-of-3 repetition before accepting
            cand_ec.append(ec)
            cand_ph.append(ph)
            cand_tp.append(tp)

            # Epsilons (tune)
            EC_EPS = 0.10
            PH_EPS = 0.20
            TP_EPS = 1.00

            # Count how many in candidate buffer are close to the latest candidate
            base_ec, base_ph, base_tp = cand_ec[-1], cand_ph[-1], cand_tp[-1]
            ok_ec = sum(within_eps(v, base_ec, EC_EPS) for v in cand_ec)
            ok_ph = sum(within_eps(v, base_ph, PH_EPS) for v in cand_ph)
            ok_tp = sum(within_eps(v, base_tp, TP_EPS) for v in cand_tp)

            if ok_ec >= CONFIRM_M and ok_ph >= CONFIRM_M and ok_tp >= CONFIRM_M:
                # Accept after confirmation
                rep_ec, rep_ph, rep_tp = base_ec, base_ph, base_tp
                win_ec.append(rep_ec); win_ph.append(rep_ph); win_tp.append(rep_tp)
                cand_ec.clear(); cand_ph.clear(); cand_tp.clear()
            else:
                # Not confirmed yet -> keep waiting
                continue

        else:
            # Normal path: accept immediately
            rep_ec, rep_ph, rep_tp = ec, ph, tp
            win_ec.append(rep_ec); win_ph.append(rep_ph); win_tp.append(rep_tp)
            cand_ec.clear(); cand_ph.clear(); cand_tp.clear()

        # 5) Report & CSV save at interval (once per minute)
        now = datetime.datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")

        if (now.minute % REPORT_MINUTES == 0) and (last_report_minute != minute_key):
            if rep_ec is not None and rep_ph is not None and rep_tp is not None:
                try:
                    append_csv_row(CSV_PATH, minute_key, rep_ec, rep_ph, rep_tp)
                except Exception as e:
                    # Do not write errors to CSV; log to stderr only
                    print(f"[csv_write_failed] {e}", file=sys.stderr, flush=True)

            # Only one-line JSON on stdout (safe for Node-RED json node)
            print(json.dumps({
                "date": minute_key,
                "EC": rep_ec,
                "pH": rep_ph,
                "Solution_Temperature": rep_tp
            }, ensure_ascii=False), flush=True)

            last_report_minute = minute_key

if __name__ == "__main__":
    main()