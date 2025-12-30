# -*- coding: utf-8 -*-
import os
import time
import csv
import json
import datetime
import minimalmodbus
import serial
import fcntl
import sys
import select

# ===============================
# Settings
# ===============================

# RS485 (Modbus RTU) port and slave address for EC/pH sensor
EC_PH_PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0"
SLAVE_ID = 1

# Log file paths
SENSOR_CSV = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_1_EC_pH_log.csv"
INJECT_CSV = "/home/cja/Work/cja-skyfarms-project/sensors/Dist_1_Solution_input_log.csv"

# Averaging window settings
DURATION_SEC = 20
INTERVAL_SEC = 1

# Control interval (test mode: every N minutes)
CHECK_INTERVAL_HOUR = 4
# CHECK_INTERVAL_MINUTE = 1

# Thresholds
EC_MIN = 0.7
PH_MAX = 6.5
# EC_MIN = 1.5
# PH_MAX = 5

# Pump calibration (ml per second) and dosing volume
PUMP_ML_PER_SEC = 1.65
DOSE_ML = 10.0

# GPIO pins (BCM)
# NOTE: Test pins (replace with actual pins when deploying)
PIN_AB = 17
PIN_ACID = 21
# PIN_AB = 22
# PIN_ACID = 23

# ===============================
# GPIO setup (RPi)
# ===============================
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    # Active-low relay: LOW=ON, HIGH=OFF
    GPIO.setup(PIN_AB, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.setup(PIN_ACID, GPIO.OUT, initial=GPIO.HIGH)
    GPIO_OK = True
except Exception as e:
    GPIO_OK = False
    GPIO_ERR = str(e)

# ===============================
# Modbus setup
# ===============================
dev = minimalmodbus.Instrument(EC_PH_PORT, SLAVE_ID, mode="rtu")
dev.serial.baudrate = 9600
dev.serial.bytesize = 8
dev.serial.parity   = serial.PARITY_NONE
dev.serial.stopbits = 2
dev.serial.timeout  = 1
dev.clear_buffers_before_each_transaction = True

# ===============================
# Node-RED switch (stdin) handling
# ===============================
def read_payload():
    """
    Non-blocking stdin read for Node-RED pythonshell input.
    Expected values:
      - "true"  -> keep running (Auto ON)
      - "false" -> stop immediately (Auto OFF)
    Returns:
      True / False / None (if no new input)
    """
    if select.select([sys.stdin], [], [], 0)[0]:
        raw = sys.stdin.readline().strip().lower()
        if raw == "true":
            return True
        if raw == "false":
            return False
    return None

def force_pumps_off():
    """Safety function: force both pumps OFF."""
    if GPIO_OK:
        GPIO.output(PIN_AB, GPIO.HIGH)
        GPIO.output(PIN_ACID, GPIO.HIGH)

# ===============================
# CSV helpers
# ===============================
def ensure_csv_ready_sensor(path: str):
    """Create directory and write header for sensor CSV if missing/empty."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    need_header = (not os.path.exists(path)) or (os.path.getsize(path) == 0)
    if need_header:
        with open(path, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "EC", "pH", "Solution_Temperature"])

def ensure_csv_ready_inject(path: str):
    """Create directory and write header for injection CSV if missing/empty."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    need_header = (not os.path.exists(path)) or (os.path.getsize(path) == 0)
    if need_header:
        with open(path, mode="a", newline="") as f:
            # Keep the same style header as your Node-RED file node
            f.write("timestamp,device,action,detail\n")

def now_str(sec=True) -> str:
    """Return current timestamp string."""
    fmt = "%Y-%m-%d %H:%M:%S" if sec else "%Y-%m-%d %H:%M"
    return datetime.datetime.now().strftime(fmt)

# ===============================
# Sensor read
# ===============================
def safe_read_once():
    """
    Read EC, pH, and solution temperature once.
    Returns:
      (ec, ph, temp) as floats, or (None, None, None) if read fails.
    """
    try:
        ph_raw = dev.read_register(0x00, 2, functioncode=3)
        ec_raw = dev.read_register(0x01, 2, functioncode=3) / 10.0
        temp_raw = dev.read_register(0x02, 2, functioncode=3) * 10.0
        return float(ec_raw), float(ph_raw), float(temp_raw)
    except Exception:
        return None, None, None

def average_ec_ph_temp():
    """
    Collect readings for DURATION_SEC and return averaged values.
    Also checks switch OFF during averaging and aborts immediately.
    Returns:
      ("OK", avg_ec, avg_ph, avg_temp)
      ("FAIL", None, None, None) on sensor read failure
      ("STOP", None, None, None) if switch turned OFF
    """
    ec_list, ph_list, temp_list = [], [], []
    start = time.monotonic()
    next_tick = start

    while True:
        sw = read_payload()
        if sw is False:
            return "STOP", None, None, None

        ec, ph, temp = safe_read_once()
        if ec is not None and ph is not None and temp is not None:
            ec_list.append(ec)
            ph_list.append(ph)
            temp_list.append(temp)

        if time.monotonic() - start >= DURATION_SEC:
            break

        next_tick += INTERVAL_SEC
        time.sleep(max(0, next_tick - time.monotonic()))

    if not ec_list or not ph_list or not temp_list:
        return "FAIL", None, None, None

    avg_ec = round(sum(ec_list) / len(ec_list), 2)
    # pH calibration correction based on your existing formula
    avg_ph = round(0.9926 * (sum(ph_list) / len(ph_list)) - 0.2488, 2)
    avg_temp = round(sum(temp_list) / len(temp_list), 2)

    return "OK", avg_ec, avg_ph, avg_temp

def log_sensor(date_str, ec, ph, temp):
    """Append one sensor row to SENSOR_CSV."""
    with open(SENSOR_CSV, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([date_str, ec, ph, temp])
        f.flush()
        os.fsync(f.fileno())

def log_injection(device: str, ml: float, sec: float):
    """
    Append injection log to INJECT_CSV in the same style as your Node-RED file output.
    Example:
      '2025-12-23 12:34:56,AB,volume,10ml,duration,6.1s'
    """
    ts = now_str(sec=True)
    sec_disp = round(sec, 1)
    line = f"{ts},{device},volume,{ml},duration,{sec_disp}s\n"
    with open(INJECT_CSV, mode="a", newline="") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())

# ===============================
# Pump control
# ===============================
def run_pump(pin: int, seconds: float):
    """
    Run one pump for the given duration.
    Active-low relay: LOW=ON, HIGH=OFF.
    Also monitors switch OFF during pumping and aborts immediately.
    """
    if not GPIO_OK:
        raise RuntimeError(f"GPIO not available: {GPIO_ERR}")

    GPIO.output(pin, GPIO.LOW)  # ON
    t0 = time.monotonic()

    try:
        while (time.monotonic() - t0) < max(0.0, seconds):
            sw = read_payload()
            if sw is False:
                raise RuntimeError("auto_switch_off")
            time.sleep(0.05)  # Check every 50ms
    finally:
        GPIO.output(pin, GPIO.HIGH)  # OFF (always)

# ===============================
# One control cycle
# ===============================
def control_once():
    """
    One control cycle:
      1) Lock RS485 bus (avoid Modbus collisions)
      2) Read averaged EC/pH/temp
      3) Log sensor row
      4) If EC < EC_MIN -> inject AB (10 ml)
         If pH >= PH_MAX -> inject Acid (10 ml)
      5) Log injections to INJECT_CSV
      6) Print JSON output for Node-RED
    """
    lock = open("/tmp/rs485_bus.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)

    try:
        ensure_csv_ready_sensor(SENSOR_CSV)
        ensure_csv_ready_inject(INJECT_CSV)

        status, avg_ec, avg_ph, avg_temp = average_ec_ph_temp()
        date_str = now_str(sec=False)

        if status == "STOP":
            print(json.dumps({"stopped": True, "reason": "switch_off"}, ensure_ascii=False), flush=True)
            return "STOP"

        if status == "FAIL" or avg_ec is None:
            print(json.dumps({"error": "sensor_read_failed"}, ensure_ascii=False), flush=True)
            return "FAIL"

        # Always log sensor reading
        log_sensor(date_str, avg_ec, avg_ph, avg_temp)

        injected = {"AB_ml": 0.0, "Acid_ml": 0.0}
        sec_needed = DOSE_ML / PUMP_ML_PER_SEC

        # Control logic
        if avg_ec < EC_MIN:
            run_pump(PIN_AB, sec_needed)
            log_injection("AB", DOSE_ML, sec_needed)
            injected["AB_ml"] = DOSE_ML

        if avg_ph >= PH_MAX:
            run_pump(PIN_ACID, sec_needed)
            log_injection("Acid", DOSE_ML, sec_needed)
            injected["Acid_ml"] = DOSE_ML

        # Node-RED JSON output
        print(json.dumps({
            "date": date_str,
            "EC": avg_ec,
            "pH": avg_ph,
            "Solution_Temperature": avg_temp,
            "injected": injected
        }, ensure_ascii=False), flush=True)

        return "OK"

    except Exception as e:
        # Special case: switch OFF during pump run
        if str(e) == "auto_switch_off":
            force_pumps_off()
            print(json.dumps({"stopped": True, "reason": "switch_off_during_pump"}, ensure_ascii=False), flush=True)
            return "STOP"

        print(json.dumps({"error": str(e)}, ensure_ascii=False), flush=True)
        return "FAIL"

    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        except:
            pass

# ===============================
# Main loop (runs while switch is ON)
# ===============================
def main_loop():
    """
    Controller-style stdin control:
      - Wait until we receive "true" (Auto ON) to start.
      - While running, if "false" arrives (Auto OFF), stop immediately.
    """
    # Wait for initial ON signal
    while True:
        sw = read_payload()
        if sw is True:
            break
        if sw is False:
            force_pumps_off()
            print(json.dumps({"stopped": True, "reason": "initial_off"}, ensure_ascii=False), flush=True)
            return
        time.sleep(0.1)

    last_slot = None  # (YYYY-MM-DD, minute) for test mode

    try:
        while True:
            # Stop immediately if switch OFF arrives
            sw = read_payload()
            if sw is False:
                force_pumps_off()
                print(json.dumps({"stopped": True, "reason": "switch_off"}, ensure_ascii=False), flush=True)
                break

            now = datetime.datetime.now()
            slot = (now.strftime("%Y-%m-%d"), now.hour)  # hour-based slots
            # slot = (now.strftime("%Y-%m-%d"), now.minute)  # test: minute-based slots

            if (now.hour % CHECK_INTERVAL_HOUR == 0) and (slot != last_slot):
            # if (now.minute % CHECK_INTERVAL_MINUTE == 0) and (slot != last_slot):
                res = control_once()
                last_slot = slot
                if res == "STOP":
                    break

            time.sleep(0.2)  # Fast polling to react quickly to OFF
    finally:
        force_pumps_off()
        if GPIO_OK:
            GPIO.cleanup()

if __name__ == "__main__":
    main_loop()