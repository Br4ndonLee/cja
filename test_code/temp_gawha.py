# -*- coding: utf-8 -*-
import json
import time
import serial

PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:1.2:1.0-port0"
BAUD = 115200
REQ  = "node000000|SensorReq|0905"

def read_one_response(ser, timeout=1.5, idle_gap=0.2):
    """Read until no more bytes arrive for a short idle gap (no newline protocol)."""
    ser.timeout = idle_gap
    buf = bytearray()
    t0 = time.time()
    last_rx = time.time()

    while time.time() - t0 < timeout:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            last_rx = time.time()
        else:
            if buf and (time.time() - last_rx) > idle_gap:
                break
    return bytes(buf)

if __name__ == "__main__":
    try:
        with serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0.2) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            ser.write(REQ.encode("ascii", errors="ignore"))
            ser.flush()

            raw = read_one_response(ser, timeout=2.5, idle_gap=0.2)

        # Show everything without parsing
        text = raw.replace(b"\x00", b"").decode("utf-8", errors="replace").strip()

        print(json.dumps({
            "req": REQ,
            "port": PORT,
            "baud": BAUD,
            "raw_len": len(raw),
            "text": text
        }, ensure_ascii=False), flush=True)

    except Exception as e:
        print(json.dumps({
            "error": str(e),
            "port": PORT,
            "baud": BAUD,
            "req": REQ
        }, ensure_ascii=False), flush=True)