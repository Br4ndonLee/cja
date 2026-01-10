# -*- coding: utf-8 -*-
import minimalmodbus
import serial
import json

# ===============================
# Modbus device setting
# ===============================

# EC_PH_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
EC_PH_PORT = "/dev/serial/by-path/platform-xhci-hcd.1-usb-0:2:1.0-port0"

dev = minimalmodbus.Instrument(EC_PH_PORT, 1, mode='rtu')


dev.serial.baudrate = 9600
dev.serial.bytesize = 8
dev.serial.parity   = serial.PARITY_NONE
dev.serial.stopbits = 1
dev.serial.timeout  = 1

# ===============================
# Read registers 0x00 ~ 0x07
# ===============================
def read_all_registers():
    try:
        data = {}

        data["pH"] = dev.read_register(0x00, 2, functioncode=3)
        data["EC"] = dev.read_register(0x01, 2, functioncode=3) / 10
        data["Solution_Temperature"] = dev.read_register(0x02, 2, functioncode=3) * 10

        for addr in range(0x02, 0x08):
            raw = dev.read_register(addr, 2, functioncode=3)
            data[f"raw_{addr:02X}"] = raw

        return data

    except Exception as e:
        return {"error": str(e)}

# ===============================

# ===============================
if __name__ == "__main__":
    result = read_all_registers()
    print(json.dumps(result, ensure_ascii=False), flush=True)
