# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import datetime
import sys
import json
import pause
import select
import os
import csv

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(5, GPIO.OUT)

CSV_DIR = "/home/cja/Work/cja-skyfarms-project/data"
CSV_PATH = os.path.join(CSV_DIR, "Dist_1_pump_activate_result.csv")

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
                GPIO.output(5, True)
                result["pump_status"] = "OFF"
                result["condition"] = "Switch turned ON, exiting loop"
                print(json.dumps(result))
                break

            # Time-based control
            if 0 <= now.minute < 5 or 30 <= now.minute < 35:
                GPIO.output(5, False)
                result["pump_status"] = "ON"
                result["condition"] = "Time OK: Pump ON"

                # Log ON once per minute to avoid duplicates (loop runs every 5 seconds)
                current_minute_key = now.strftime("%Y/%m/%d %H:%M")
                if last_on_minute != current_minute_key:
                    log_pump_on(timestamp_csv)
                    last_on_minute = current_minute_key

            else:
                GPIO.output(5, True)
                result["pump_status"] = "OFF"
                result["condition"] = "Time OUT: Pump OFF"

            print(json.dumps(result))
            pause.seconds(5)

    else:
        GPIO.output(5, True)
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
