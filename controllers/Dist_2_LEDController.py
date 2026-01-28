    # # -*- coding: utf-8 -*-
    # import RPi.GPIO as GPIO
    # import datetime
    # import sys
    # import json
    # import pause
    # import select

    # GPIO.setwarnings(False)
    # GPIO.setmode(GPIO.BCM)
    # GPIO.setup(26, GPIO.OUT)
    # GPIO.setup(24, GPIO.OUT)
    # GPIO.setup(25, GPIO.OUT)

    # def read_payload():
    #     # Non-blocking stdin check
    #     if select.select([sys.stdin], [], [], 0)[0]:
    #         raw_payload = sys.stdin.readline().strip().lower()
    #         if raw_payload == "true":
    #             return True
    #         elif raw_payload == "false":
    #             return False
    #     return None

    # try:
    #     first_input = read_payload()
    #     if first_input is False:
    #         while True:
    #             now = datetime.datetime.now()
    #             timestamp = now.strftime('%Y-%m-%d %H:%M')
    #             result = {
    #                 "timestamp": timestamp,
    #                 "led_status": None,
    #                 "condition": None
    #             }

    #             # Check for new payload input (non-blocking)
    #             new_input = read_payload()
    #             if new_input is True:
    #                 GPIO.output(24, True)
    #                 GPIO.output(25, True)
    #                 GPIO.output(26, True)
    #                 result["led_status"] = "OFF"
    #                 result["condition"] = "Switch turned ON, exiting loop"
    #                 print(json.dumps(result))
    #                 break

    #             # Time-based control
    #             if 4 <= now.hour < 22:
    #             # if 0 <= now.second < 30:
    #                 GPIO.output(24, False)
    #                 GPIO.output(25, False)
    #                 GPIO.output(26, False)
    #                 result["led_status"] = "ON"
    #                 result["condition"] = "Time OK: LED ON"
    #             else:
    #                 GPIO.output(24, True)
    #                 GPIO.output(25, True)
    #                 GPIO.output(26, True)
    #                 result["led_status"] = "OFF"
    #                 result["condition"] = "Time OUT: LED OFF"

    #             print(json.dumps(result))
    #             pause.seconds(5)

    #     else:
    #         GPIO.output(24, True)
    #         GPIO.output(25, True)
    #         GPIO.output(26, True)
    #         result = {
    #             "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
    #             "led_status": "OFF",
    #             "condition": "Initial input was TRUE: force OFF"
    #         }
    #         print(json.dumps(result))

    # except KeyboardInterrupt:
    #     print("Stopped manually")

    # finally:
    #     GPIO.cleanup()

# # -*- coding: utf-8 -*-
# import RPi.GPIO as GPIO
# import datetime
# import sys
# import json
# import pause
# import select

# GPIO.setwarnings(False)
# GPIO.setmode(GPIO.BCM)
# GPIO.setup(4, GPIO.OUT)
# # GPIO.setup(6, GPIO.OUT)

# def read_payload():
#     # Non-blocking stdin check
#     if select.select([sys.stdin], [], [], 0)[0]:
#         raw_payload = sys.stdin.readline().strip().lower()
#         if raw_payload == "true":
#             return True
#         elif raw_payload == "false":
#             return False
#     return None

# try:
#     first_input = read_payload()
#     if first_input is False:
#         while True:
#             now = datetime.datetime.now()
#             timestamp = now.strftime('%Y-%m-%d %H:%M')
#             result = {
#                 "timestamp": timestamp,
#                 "led_status": None,
#                 "condition": None
#             }

#             # Check for new payload input (non-blocking)
#             new_input = read_payload()
#             if new_input is True:
#                 GPIO.output(4, True)
#                 # GPIO.output(6, True)
#                 # result["led_status"] = "OFF"
#                 # result["condition"] = "Switch turned ON, exiting loop"
#                 # print(json.dumps(result))
#                 break

#             # Time-based control
#             if 4 <= now.hour < 22:
#             # if 0 <= now.second < 30:
#                 GPIO.output(4, False)
#                 # GPIO.output(6, False)
#                 # result["led_status"] = "ON"
#                 # result["condition"] = "Time OK: LED ON"
#             else:
#                 GPIO.output(4, True)
#                 # GPIO.output(6, True)    
#                 # result["led_status"] = "OFF"
#                 # result["condition"] = "Time OUT: LED OFF"

#             # print(json.dumps(result))
#             pause.seconds(5)

#     else:
#         GPIO.output(4, True)
#         # GPIO.output(6, True)
#         # result = {
#         #     "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
#         #     "led_status": "OFF",
#         #     "condition": "Initial input was TRUE: force OFF"
#         # }
#         # print(json.dumps(result))

# except KeyboardInterrupt:
#     print("Stopped manually")

# finally:
#     GPIO.cleanup()

########################################################################################################################
# -*- coding: utf-8 -*-
import RPi.GPIO as GPIO
import datetime
import sys
import time
import select

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(26, GPIO.OUT)
GPIO.setup(24, GPIO.OUT)
GPIO.setup(25, GPIO.OUT)

# Active-low relay assumption:
#   GPIO False(0) -> ON
#   GPIO True(1)  -> OFF
GPIO_ON = False
GPIO_OFF = True

def read_payload():
    # Non-blocking stdin check
    if select.select([sys.stdin], [], [], 0)[0]:
        raw_payload = sys.stdin.readline().strip().lower()
        if raw_payload == "true":
            return True
        if raw_payload == "false":
            return False
    return None

def time_allows_led(now: datetime.datetime) -> bool:
    # LED ON between 04:00 and 21:59
    return (4 <= now.hour < 22)

try:
    # Start safe (OFF)
    GPIO.output(26, GPIO_OFF)
    GPIO.output(24, GPIO_OFF)
    GPIO.output(25, GPIO_OFF)

    # We keep last commanded auto_mode:
    # auto_mode == True  -> run time-based control
    # auto_mode == False -> force OFF
    auto_mode = False

    # Wait until we receive an initial command from Node-RED
    # (prevents "None => else => OFF forever" behavior)
    while True:
        cmd = read_payload()
        if cmd is not None:
            # Your original convention:
            #   "false" => start auto loop
            #   "true"  => stop / exit auto loop
            auto_mode = (cmd is False)
            break
        time.sleep(0.05)

    while True:
        # Check for new command quickly
        cmd = read_payload()
        if cmd is True:
            # Stop mode: force OFF and keep waiting (no exit)
            auto_mode = False
        elif cmd is False:
            # Auto mode: enable time-based control
            auto_mode = True

        now = datetime.datetime.now()

        if auto_mode:
            # Time-based control
            if time_allows_led(now):
                GPIO.output(26, GPIO_ON)
                GPIO.output(24, GPIO_ON)
                GPIO.output(25, GPIO_ON)
            else:
                GPIO.output(26, GPIO_OFF)
                GPIO.output(24, GPIO_OFF)
                GPIO.output(25, GPIO_OFF)
        else:
            # Forced OFF when not in auto_mode
            GPIO.output(26, GPIO_OFF)
            GPIO.output(24, GPIO_OFF)
            GPIO.output(25, GPIO_OFF)

        # Polling interval (responsive but low CPU)
        time.sleep(0.2)

except KeyboardInterrupt:
    # Keep silent (avoid stdout spam in Node-RED)
    pass

finally:
    # Always leave OFF
    try:
        GPIO.output(26, GPIO_OFF)
        GPIO.output(24, GPIO_OFF)
        GPIO.output(25, GPIO_OFF)
    except Exception:
        pass
    GPIO.cleanup()