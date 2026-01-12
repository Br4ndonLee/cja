# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import datetime
import sys
import json
import pause
import select
import os
import csv

PUMP_1_PIN = 6
PUMP_2_PIN = 12

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(PUMP_1_PIN, GPIO.OUT)
GPIO.setup(PUMP_2_PIN, GPIO.OUT)

CSV_DIR = "/home/cja/Work/cja-skyfarms-project/data"
CSV_PATH = os.path.join(CSV_DIR, "Dist_2_pump_activate_result.csv")

last_on_minute = None

def ensure_csv_dir():
    os.makedirs(CSV_DIR, exist_ok=True)

def log_pump_on(ts_str):
    ensure_csv_dir()
    with open(CSV_PATH, mode="a", newline="") as f:
        w = csv.writer(f)
        w.writerow([ts_str, "On"])
        f.flush()
        os.fsync(f.fileno())

def read_payload():
    # Non-blocking stdin check
    if select.select([sys.stdin], [], [], 0)[0]:
        raw_payload = sys.stdin.readline().strip().lower()
        if raw_payload == "true":
            return True
        elif raw_payload == "false":
            return False
    return None

try:
    first_input = read_payload()
    if first_input is False:
        while True:
            now = datetime.datetime.now()
            timestamp_json = now.strftime('%Y-%m-%d %H:%M')
            timestamp_csv = now.strftime('%Y/%m/%d %H:%M')

            result = {
                "timestamp": timestamp_json,
                "pump_status": None,
                "condition": None
            }

            # Check for new payload input (non-blocking)
            new_input = read_payload()
            if new_input is True:
                GPIO.output(PUMP_1_PIN, True)
                GPIO.output(PUMP_2_PIN, True)
                result["pump_status"] = "OFF"
                result["condition"] = "Switch turned ON, exiting loop"
                print(json.dumps(result))
                break

            # Time-based control
            if 0 <= now.minute < 2 or 20 <= now.minute < 22 or 40 <= now.minute < 42:
                GPIO.output(PUMP_1_PIN, False)
                GPIO.output(PUMP_2_PIN, False)
                result["pump_status"] = "ON"
                result["condition"] = "Time OK: Pump ON"

                # Log ON once per minute to avoid duplicates (loop runs every 5 seconds)
                current_minute_key = now.strftime("%Y/%m/%d %H:%M")
                if last_on_minute != current_minute_key:
                    log_pump_on(timestamp_csv)
                    last_on_minute = current_minute_key

            else:
                GPIO.output(PUMP_1_PIN, True)
                GPIO.output(PUMP_2_PIN, True)
                result["pump_status"] = "OFF"
                result["condition"] = "Time OUT: Pump OFF"

            print(json.dumps(result))
            pause.seconds(5)

    else:
        GPIO.output(PUMP_1_PIN, True)
        GPIO.output(PUMP_2_PIN, True)
        result = {
            "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            "pump_status": "OFF",
            "condition": "Initial input was TRUE: force OFF"
        }
        print(json.dumps(result))

except KeyboardInterrupt:
    print("Stopped manually")

finally:
    GPIO.cleanup()
