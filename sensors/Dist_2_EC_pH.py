# -*- coding: utf-8 -*-
import os
import csv
import json
import time
import datetime
import serial
import fcntl
import re
import math
from serial.serialutil import SerialException

# ===============================
# Settings
# ===============================
PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:1.2:1.0-port0"
BAUD = 115200
REQ  = "node000300|SensorReq|8985"

# Target sensor IDs (expected)
ID_PH   = 16
ID_TEMP = 29
ID_EC   = 30

CSV_PATH = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_2_EC_pH_log.csv"
SERIAL_LOCK_PATH = "/tmp/usb_1a86_serial.lock"

TOTAL_TIMEOUT_SEC = 3.0
IDLE_GAP_SEC = 0.2
RETRY_ATTEMPTS = 3
RETRY_DELAY_SEC = 0.25

# Poll / report / save
POLL_SEC = 10
JSON_EVERY_MIN = 3
CSV_EVERY_MIN = 20

# ===============================
# Physical validity ranges (safe)
# ===============================
# NOTE: Adjust if your system uses different EC units/ranges.
VALID_EC_MIN, VALID_EC_MAX = 0.00, 5.00        # dS/m
VALID_PH_MIN, VALID_PH_MAX = 2.00, 10.00       # pH
VALID_TP_MIN, VALID_TP_MAX = 10.00, 50.00      # ¡ÆC

# ===============================
# Hampel filter settings
# ===============================
HAMPEL_WIN = 15          # 15 samples * 10s = 150s
HAMPEL_K = 3.0

# ===============================
# Confirmation settings
# ===============================
CONFIRM_N = 3
CONFIRM_M = 2
EC_BAND_ABS = 0.20
PH_BAND_ABS = 0.50
TP_BAND_ABS = 2.0

# ===============================
# Timing helpers (no drift)
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

# ===============================
# Robust number parsing
# ===============================
def fix_slash_number(s: str) -> str:
    """
    Fix common corruption patterns:
      - "17/10" -> "17.10"
      - "1/05"  -> "1.05"
      - "0/0"   -> "0.0"
    """
    s = s.strip()
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return parts[0] + "." + parts[1]
    return s

def to_float_maybe(s: str):
    """Try to convert a corrupted numeric string to float."""
    if s is None:
        return None
    s2 = fix_slash_number(str(s))
    s2 = s2.replace(" ", "")
    s2 = re.sub(r"[^0-9\.\-]", "", s2)
    if not s2:
        return None
    try:
        v = float(s2)
        if math.isfinite(v):
            return v
    except:
        return None
    return None

def extract_value_for_id(text: str, target_id: int):
    """
    Try to extract the numeric value that follows a given id.
    Works even if quotes/colons are partially corrupted, as long as 'id' + digits survive.
    """
    m = re.search(
        r'(?:id)[^0-9]{0,10}' + re.escape(str(target_id)) + r'[^0-9]{0,100}',
        text,
        re.IGNORECASE
    )
    if not m:
        return None

    window = text[m.start(): m.start() + 260]

    mv = re.search(r'(?:value)[^0-9]{0,30}([0-9]+(?:[./][0-9]+)?)', window, re.IGNORECASE)
    if mv:
        return to_float_maybe(mv.group(1))

    mn = re.search(r'([0-9]+(?:[./][0-9]+)?)', window)
    if mn:
        return to_float_maybe(mn.group(1))

    return None

def parse_ec_ph_tp(text: str):
    """
    Primary: ID-based extraction
    Fallback: scan near "sensors" and assign by physical ranges
    """
    ec = extract_value_for_id(text, ID_EC)
    ph = extract_value_for_id(text, ID_PH)
    tp = extract_value_for_id(text, ID_TEMP)

    if ec is not None and ph is not None and tp is not None:
        return ec, ph, tp

    lower = text.lower()
    i = lower.find("sensors")
    chunk = text[i:i+600] if i != -1 else text

    nums = []
    for mm in re.finditer(r'([0-9]+(?:[./][0-9]+)?)', chunk):
        v = to_float_maybe(mm.group(1))
        if v is not None:
            nums.append(v)

    for v in nums:
        if ph is None and (VALID_PH_MIN <= v <= VALID_PH_MAX):
            ph = v
            continue
        if tp is None and (VALID_TP_MIN <= v <= VALID_TP_MAX):
            tp = v
            continue
        if ec is None and (VALID_EC_MIN <= v <= VALID_EC_MAX):
            ec = v
            continue
        if ec is not None and ph is not None and tp is not None:
            break

    return ec, ph, tp

# ===============================
# Read one request with lock + retry
# ===============================
def request_once_with_lock_and_retry():
    """
    Lock bus -> open serial -> request once -> parse -> retry.
    Returns (ec, ph, tp, err_string_or_None, head_text).
    """
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
                    last_head = text[:180]

                    ec, ph, tp = parse_ec_ph_tp(text)

                    if ec is None and ph is None and tp is None:
                        last_err = "value_missing_all"
                        time.sleep(RETRY_DELAY_SEC)
                        continue

                    return ec, ph, tp, None, last_head

            except (SerialException, OSError) as e:
                last_err = f"serial_error: {e}"
                time.sleep(RETRY_DELAY_SEC)
            except Exception as e:
                last_err = f"unknown_error: {e}"
                time.sleep(RETRY_DELAY_SEC)

        return None, None, None, last_err, last_head

    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        except:
            pass
        lockf.close()

# ===============================
# Filtering helpers
# ===============================
def is_finite_number(x) -> bool:
    """Check x is a finite float-like number."""
    try:
        xf = float(x)
        return math.isfinite(xf)
    except:
        return False

def valid_ec(x) -> bool:
    return is_finite_number(x) and (VALID_EC_MIN <= float(x) <= VALID_EC_MAX)

def valid_ph(x) -> bool:
    return is_finite_number(x) and (VALID_PH_MIN <= float(x) <= VALID_PH_MAX)

def valid_tp(x) -> bool:
    return is_finite_number(x) and (VALID_TP_MIN <= float(x) <= VALID_TP_MAX)

def median(values):
    """Compute median for a list of floats."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])

def mad(values, med):
    """Median absolute deviation."""
    dev = [abs(v - med) for v in values]
    return median(dev)

def hampel_accept(candidate, history, k=3.0):
    """Hampel decision (True = accept)."""
    if not is_finite_number(candidate):
        return False
    c = float(candidate)

    if len(history) < max(5, HAMPEL_WIN // 3):
        return True

    window = history[-HAMPEL_WIN:]
    m = median(window)
    if m is None:
        return True

    mad_v = mad(window, m)
    if mad_v is None:
        return True

    sigma = 1.4826 * mad_v
    if sigma == 0:
        return abs(c - m) < 1e-9

    return abs(c - m) <= (k * sigma)

def within_band(a, b, band_abs):
    """Check if two values are close enough."""
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= float(band_abs)
    except:
        return False

def confirmation_update(rep, pending_list, candidate, band_abs, n=3, m=2):
    """M-of-N confirmation promotion."""
    c = float(candidate)

    if rep is None:
        return c, [], "accepted_first"

    if within_band(c, rep, band_abs):
        return c, [], "accepted_near_rep"

    pending_list = (pending_list + [c])[-n:]
    pm = median(pending_list)
    if pm is None:
        return rep, pending_list, "pending"

    close = [x for x in pending_list if abs(x - pm) <= band_abs]
    if len(close) >= m:
        new_rep = median(close)
        return new_rep, [], "promoted_confirmed"

    return rep, pending_list, "pending"

# ===============================
# Main loop
# ===============================
def main():
    ensure_csv_header(CSV_PATH)

    # Histories for Hampel (accepted samples only)
    hist_ec, hist_ph, hist_tp = [], [], []

    # Representatives (confirmed) - updated per-variable independently
    rep_ec = rep_ph = rep_tp = None

    # Pending for confirmation
    pend_ec, pend_ph, pend_tp = [], [], []

    last_json_minute = None
    last_csv_minute = None
    last_err = None

    # Start message (Node-RED liveness)
    print(json.dumps({
        "type": "started",
        "port": PORT,
        "baud": BAUD,
        "req": REQ,
        "json_every_min": JSON_EVERY_MIN,
        "csv_every_min": CSV_EVERY_MIN
    }, ensure_ascii=False), flush=True)

    while True:
        # 1) Poll every 10 seconds (no drift)
        sleep_to_next_boundary(POLL_SEC)

        ec, ph, tp, err, head = request_once_with_lock_and_retry()
        if err is not None:
            last_err = err
        else:
            updated_any = False

            # EC
            if valid_ec(ec):
                ec = float(ec)
                if hampel_accept(ec, hist_ec, HAMPEL_K):
                    hist_ec.append(ec)
                    hist_ec = hist_ec[-(HAMPEL_WIN * 3):]
                    rep_ec, pend_ec, _ = confirmation_update(rep_ec, pend_ec, ec, EC_BAND_ABS, CONFIRM_N, CONFIRM_M)
                    updated_any = True
                else:
                    last_err = "hampel_outlier_ec"

            # pH (allow missing/invalid, do NOT block others)
            if valid_ph(ph):
                ph = float(ph)
                if hampel_accept(ph, hist_ph, HAMPEL_K):
                    hist_ph.append(ph)
                    hist_ph = hist_ph[-(HAMPEL_WIN * 3):]
                    rep_ph, pend_ph, _ = confirmation_update(rep_ph, pend_ph, ph, PH_BAND_ABS, CONFIRM_N, CONFIRM_M)
                    updated_any = True
                else:
                    last_err = "hampel_outlier_ph"
            else:
                # pH=0.0 is common in your corrupted frames -> invalid by design
                if ph is not None and is_finite_number(ph) and float(ph) != 0.0:
                    last_err = "invalid_ph"

            # Temp
            if valid_tp(tp):
                tp = float(tp)
                if hampel_accept(tp, hist_tp, HAMPEL_K):
                    hist_tp.append(tp)
                    hist_tp = hist_tp[-(HAMPEL_WIN * 3):]
                    rep_tp, pend_tp, _ = confirmation_update(rep_tp, pend_tp, tp, TP_BAND_ABS, CONFIRM_N, CONFIRM_M)
                    updated_any = True
                else:
                    last_err = "hampel_outlier_tp"

            if updated_any:
                # If we got at least one good update, clear stale error
                last_err = None

        now = datetime.datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")

        # 2) JSON output every 3 minutes (exactly once per minute)
        if (now.minute % JSON_EVERY_MIN == 0) and (last_json_minute != minute_key):
            payload = {
                "type": "report",
                "date": minute_key,
                "EC": (round(rep_ec, 2) if rep_ec is not None else None),
                "pH": (round(rep_ph, 2) if rep_ph is not None else None),
                "Solution_Temperature": (round(rep_tp, 2) if rep_tp is not None else None),
                "last_err": last_err
            }
            if payload["EC"] is None and payload["pH"] is None and payload["Solution_Temperature"] is None:
                payload["note"] = "rep_not_ready"
            print(json.dumps(payload, ensure_ascii=False), flush=True)
            last_json_minute = minute_key

        # 3) CSV save every 20 minutes (exactly once per minute)
        # Policy: Save if EC + Temp exist; pH may be blank.
        if (now.minute % CSV_EVERY_MIN == 0) and (last_csv_minute != minute_key):
            if rep_ec is not None and rep_tp is not None:
                try:
                    log_ec = round(float(rep_ec), 2)
                    log_tp = round(float(rep_tp), 2)
                    log_ph = round(float(rep_ph), 2) if rep_ph is not None else ""

                    append_csv_row(CSV_PATH, minute_key, log_ec, log_ph, log_tp)

                except Exception as e:
                    print(json.dumps({
                        "type": "csv_error",
                        "date": minute_key,
                        "error": f"csv_write_failed: {e}"
                    }, ensure_ascii=False), flush=True)
            else:
                # No EC/temp representative yet -> skip saving safely
                print(json.dumps({
                    "type": "csv_skip",
                    "date": minute_key,
                    "note": "ec_or_temp_missing",
                    "EC": (round(rep_ec, 2) if rep_ec is not None else None),
                    "Solution_Temperature": (round(rep_tp, 2) if rep_tp is not None else None)
                }, ensure_ascii=False), flush=True)

            last_csv_minute = minute_key


if __name__ == "__main__":
    main()