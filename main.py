#!/usr/bin/python3
"""
Python implementation of control system for CJA SKYFARMS
This code is designed to control the plantfactory environment.
It includes functionalities for controlling fans, circulator, nutrient solution pumps, and managing the environment.
This code is part of the CJA SKYFARMS project.
author: Sanghyun Lee
"""
import os
import time
import spidev
import pause
import RPi.GPIO as GPIO
import tkinter as tk
from datetime import datetime as dt



GPIO.setmode(GPIO.BCM)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CJA SKYFARMS Control Panel")
        self.geometry("800x600")
        self.fan_controller = DCFan.FanController(4, self.update_status)
        self.air_circulator = AirCirculator.AirCirculatorController(5, self.update_status)
        
        # Create UI elements
        self.status_label = tk.Label(self, text="Status: ", font=("Arial", 14))
        self.status_label.pack(pady=20)

        self.fan_button = tk.Button(self, text="Toggle Fans", command=self.toggle_fans, font=("Arial", 14))
        self.fan_button.pack(pady=10)

        self.circulator_button = tk.Button(self, text="Toggle Circulator", command=self.toggle_circulator, font=("Arial", 14))
        self.circulator_button.pack(pady=10)

    def update_status(self, message):
        self.status_label.config(text=f"Status: {message}")

    def toggle_fans(self):
        current_state = not GPIO.input(4)  # Assuming GPIO pin 4 is used for DC fans
        self.fan_controller.toggle_fans(current_state)

    def toggle_circulator(self):
        current_state = not GPIO.input(5)  # Assuming GPIO pin 5 is used for air circulator
        self.air_circulator.toggle_circulator(current_state)

def main():
    GPIO.setmode(GPIO.BCM)
    app = App()
    app.mainloop()
    GPIO.cleanup()





if __name__ == "__main__":
    
    main()
    