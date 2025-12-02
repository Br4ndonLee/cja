# test_modbus_probe.py
import minimalmodbus, serial, time

PORT = "/dev/serial/by-id/usb-..."  # ← 실제 값으로 교체
ADDRS = [1]                         # 필요시 [1,2,3,...]
FUNCTIONS = [4, 3]                  # 4=Input, 3=Holding
STOPBITS  = [2, 1]                  # 장비 따라 다름
BAUD = 9600
TIMEOUT = 1.5

REG = 0x00     # 시작 레지스터 (예: 0xC8 등으로 바꿔 테스트)
COUNT = 2      # 읽을 개수

def try_once(port, slave, fc, stopbits):
    dev = minimalmodbus.Instrument(port, slave, mode='rtu')
    dev.serial.baudrate = BAUD
    dev.serial.bytesize = 8
    dev.serial.parity   = serial.PARITY_NONE
    dev.serial.stopbits = stopbits
    dev.serial.timeout  = TIMEOUT
    dev.clear_buffers_before_each_transaction = True
    dev.close_port_after_each_call = True
    try:
        regs = dev.read_registers(REG, COUNT, functioncode=fc)
        return regs
    except Exception as e:
        return None

for a in ADDRS:
    for fc in FUNCTIONS:
        for sb in STOPBITS:
            print(f"Try slave={a}, fc={fc}, stopbits={sb} ... ", end="", flush=True)
            r = try_once(PORT, a, fc, sb)
            if r is not None:
                print("OK ->", r)
            else:
                print("fail")
            time.sleep(0.2)
