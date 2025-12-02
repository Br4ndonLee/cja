# -*- coding: utf-8 -*-
import os
import minimalmodbus
import serial
import datetime
import json
import csv

# Setting up the Modbus RTU client
dev1 = minimalmodbus.Instrument("/dev/ttyACM0", 1, mode='rtu')  # Slave address 1
dev1.serial.baudrate = 9600
dev1.serial.bytesize = 8
dev1.serial.parity = serial.PARITY_NONE
dev1.serial.stopbits = 2
dev1.serial.timeout = 1

# Open a CSV file for logging the results
csv_file_path = 'Temp_humi_log.csv'
with open(csv_file_path, mode='a', newline='') as file:
    writer = csv.writer(file)

    if os.stat(csv_file_path).st_size == 0:
        writer.writerow(['Date', 'Temperature', 'Humidity'])  # CSV header

    # Read two registers (temperature, humidity)
    registers = dev1.read_registers(0xC8, 2, functioncode=4)
    temp = float(registers[0]) / 10.0
    humi = float(registers[1]) / 10.0
    date = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

    writer.writerow([date, temp, humi])


    output = {
        "date": date,
        "temperature": temp,
        "humidity": humi
    }

    print(json.dumps(output))
