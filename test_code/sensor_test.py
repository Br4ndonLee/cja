# -*- coding: utf-8 -*-
import serial, time

PORT = "/dev/ttyUSB1"
BAUD = 115200
# REQ_SOLUTION  = "node000000|SensorReq|0905"  # no terminator!
REQ  = "node000000|SensorReq|0905"  # no terminator!
REQ_CONDITION  = "node000300|SensorReq|8985"  # no terminator!

with serial.Serial(
    PORT,
    baudrate=BAUD,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=1.0,
    xonxoff=False,
    rtscts=False,
    dsrdtr=False,
) as ser:
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    ser.write(REQ.encode("ascii"))
    # ser.write(REQ_SOLUTION.encode("ascii"))
    ser.write(REQ_CONDITION.encode("ascii"))
    ser.flush()

    # Read one response burst
    time.sleep(0.1)
    data = ser.read(4096)

    # Print raw + text (strip nulls)
    print("raw:", data)
    print("text:", data.replace(b"\x00", b"").decode("utf-8", errors="replace"))