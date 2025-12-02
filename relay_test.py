import RPi.GPIO as GPIO
import time

# BCM 모드 설정
GPIO.setmode(GPIO.BCM)

# GPIO 1번부터 25번까지 출력 모드로 설정
for pin in range(1, 27):
    try:
        GPIO.setup(pin, GPIO.OUT)
        print(f"GPIO {pin} setup success")
    except Exception as e:
        print(f"GPIO {pin} setup failed: {e}")

# 테스트 시작 알림
print("Start GPIO output test")

# # 각 핀에 대해 HIGH → 2초 → LOW → 2초
# for pin in range(1, 27):
#     try:
#         GPIO.output(pin, False)
#         print(f"GPIO {pin} HIGH")
#         time.sleep(2)

#         GPIO.output(pin, True)
#         print(f"GPIO {pin} LOW")
#         time.sleep(2)
#     except Exception as e:
#         print(f"GPIO {pin} output failed: {e}")

pin = 18

GPIO.output(pin, False)
print(f"GPIO {pin} HIGH")
time.sleep(2)

GPIO.output(pin, True)
print(f"GPIO {pin} LOW")
time.sleep(1)

# 사용 후 GPIO 초기화
GPIO.cleanup()
print("GPIO cleanup completed")
