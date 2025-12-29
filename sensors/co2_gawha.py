# -*- coding: utf-8 -*-
import json
import time
import serial

PORT = "/dev/serial/by-path/platform-xhci-hcd.0-usb-0:1.2:1.0-port0"
BAUD = 115200
REQ  = "node000000|SensorReq|0905"

def read_one_response(ser, timeout=1.5):
    """Read until no more bytes arrive for a short gap (no newline protocol)."""
    ser.timeout = 0.2
    buf = bytearray()
    t0 = time.time()
    last_rx = time.time()

    while time.time() - t0 < timeout:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            last_rx = time.time()
        else:
            if buf and (time.time() - last_rx) > 0.2:
                break
    return bytes(buf)

def extract_json_block(text: str) -> str | None:
    """Extract {...} part from '|SensorRes|{...}|XXXX'."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end+1]

def parse_co2_value(text: str):
    """Return CO2 value (id=6) as int if possible, else None."""
    json_part = extract_json_block(text)
    if not json_part:
        return None, "no_json_block"

    try:
        data = json.loads(json_part)
    except Exception as e:
        return None, f"json_load_error: {e}"

    sensors = data.get("sensors", [])
    for s in sensors:
        if s.get("id") == 6:
            v = str(s.get("value", "")).strip()
            # " 660" 같은 문자열 -> int 변환 시도
            try:
                return int(v), None
            except:
                try:
                    return float(v), None
                except:
                    return v, None

    return None, "id_6_not_found"

if __name__ == "__main__":
    try:
        with serial.Serial(PORT, BAUD, bytesize=8, parity="N", stopbits=1, timeout=0.2) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            ser.write(REQ.encode("ascii"))
            ser.flush()

            raw = read_one_response(ser, timeout=2.0)

        text = raw.replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()

        co2, err = parse_co2_value(text)

        if err:
            print(json.dumps({
                "error": err,
                "text": text
            }, ensure_ascii=False), flush=True)
        else:
            print(json.dumps({
                "CO2": co2
            }, ensure_ascii=False), flush=True)

    except Exception as e:
        print(json.dumps({
            "error": str(e)
        }, ensure_ascii=False), flush=True)