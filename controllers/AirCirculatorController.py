# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import datetime
import sys
import time
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

            # Check for new payload input (non-blocking)
            new_input = read_payload()
            if new_input is True:
                GPIO.output(16, True)
                break

            # # Time-based control
            # if 0 <= now.hour < 24:
            # # if 0 <= now.second < 30:
            #     GPIO.output(16, False)
            # else:
            #     GPIO.output(16, True)
            
            # Switch-based control
            else :
                GPIO.output(16, False)

                time.sleep(0.2)

    else:
        GPIO.output(16, True)

except KeyboardInterrupt:
    print("Stopped manually")

finally:
    GPIO.cleanup()
