# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import datetime
import sys
import json
import pause
import select

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(16, GPIO.OUT)

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
            timestamp = now.strftime('%Y-%m-%d %H:%M')
            result = {
                "timestamp": timestamp,
                "led_status": None,
                "condition": None
            }

            # Check for new payload input (non-blocking)
            new_input = read_payload()
            if new_input is True:
                GPIO.output(16, True)
                result["circulator_status"] = "OFF"
                result["condition"] = "Switch turned ON, exiting loop"
                print(json.dumps(result))
                break

            # # Time-based control
            # if 0 <= now.hour < 24:
            # # if 0 <= now.second < 30:
            #     GPIO.output(16, False)
            #     result["circulator_status"] = "ON"
            #     result["condition"] = "Time OK: Circulator ON"
            # else:
            #     GPIO.output(16, True)
            #     result["circulator_status"] = "OFF"
            #     result["condition"] = "Time OUT: Circulator OFF"
            
            # Switch-based control
            else :
            # if 0 <= now.second < 30:
                GPIO.output(16, False)
                result["circulator_status"] = "ON"
                result["condition"] = "Time OK: Circulator ON"


            print(json.dumps(result))
            pause.seconds(5)

    else:
        GPIO.output(16, True)
        result = {
            "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            "circulator_status": "OFF",
            "condition": "Initial input was TRUE: force OFF"
        }
        print(json.dumps(result))

except KeyboardInterrupt:
    print("Stopped manually")

finally:
    GPIO.cleanup()
