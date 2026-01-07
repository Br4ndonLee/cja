# -*- coding: utf-8 -*-
import minimalmodbus
import serial
import time

# Modbus RTU client setup
dev1 = minimalmodbus.Instrument("/dev/ttyACM2", 1, mode='rtu')  # Slave address 1
dev1.serial.baudrate = 9600
dev1.serial.bytesize = 8    # Data bits
dev1.serial.parity = serial.PARITY_NONE  # No parity
dev1.serial.stopbits = 2    # Stop bits
dev1.serial.timeout = 1     # Timeout setting

try:
    while True:
        # Read multiple register values at once (e.g., registers 0xc8, 0xc9)
        # Starting from 0x03EB, read two registers
        registers = dev1.read_registers(0xc8, 2, functioncode=4)  # Read 2 registers
        temp = float(registers[0]/10)  # First register (temperature value)
        humi = float(registers[1]/10)  # Second register (humidity value)

        print("temp = " + str(temp))
        print("humi = " + str(humi))

        # Read every 1 second
        time.sleep(1)

except Exception as e:
    print('Error: %s' % e)


