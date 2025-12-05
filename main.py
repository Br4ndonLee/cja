#!/usr/bin/python3
"""
Python implementation of control system for CJA SKYFARMS
This code is designed to control the plantfactory environment.
It includes functionalities for controlling fans, circulator, nutrient solution pumps, and managing the environment.
This code is part of the CJA SKYFARMS project.
author: Sanghyun Lee
"""
# main.py
# Tkinter-based simple dashboard that roughly mimics your Node-RED flow.

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import json
import csv
import os
import threading
import time
from datetime import datetime

import RPi.GPIO as GPIO

# ------------ GPIO setup ------------

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

PIN_MINIFAN = 13    # Mini Fan
PIN_CIRC    = 16    # Circulator
PIN_PUMP    = 25    # Nutrient solution pump (A/B/Acid common example)

# Assume active-low relay: LOW=ON, HIGH=OFF
GPIO.setup(PIN_MINIFAN, GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(PIN_CIRC,    GPIO.OUT, initial=GPIO.HIGH)
GPIO.setup(PIN_PUMP,    GPIO.OUT, initial=GPIO.HIGH)

# ------------ Paths ------------

BASE_DIR = "/home/cja/Work/cja-skyfarms-project"
TEMP_HUMI_SCRIPT = os.path.join(BASE_DIR, "sensors", "Temp_humi.py")
EC_PH_SCRIPT     = os.path.join(BASE_DIR, "sensors", "EC_pH.py")
SOLUTION_LOG_CSV = os.path.join(BASE_DIR, "sensors", "Solution_input_log.csv")

# ------------ Helper functions ------------

def run_python_script(path):
    """Run a Python script and return last non-empty line as string."""
    try:
        result = subprocess.run(
            ["python3", path],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            return None, f"Script error: {result.stderr.strip()}"
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if not lines:
            return None, "No output"
        return lines[-1], None
    except Exception as e:
        return None, f"Exception: {e}"

def ensure_solution_log():
    """Make sure solution log CSV exists with header."""
    os.makedirs(os.path.dirname(SOLUTION_LOG_CSV), exist_ok=True)
    need_header = (not os.path.exists(SOLUTION_LOG_CSV)) or (os.path.getsize(SOLUTION_LOG_CSV) == 0)
    if need_header:
        with open(SOLUTION_LOG_CSV, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "Solution", "Input volume (ml)"])

def log_solution(solution_name, volume_ml):
    """Append one line to solution log CSV."""
    ensure_solution_log()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(SOLUTION_LOG_CSV, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow([ts, solution_name, volume_ml])

# ------------ Pump control (blocking) ------------

def run_pump_blocking(duration_sec):
    """Turn pump ON for duration_sec seconds (blocking)."""
    GPIO.output(PIN_PUMP, GPIO.LOW)
    try:
        time.sleep(max(0.0, duration_sec))
    finally:
        GPIO.output(PIN_PUMP, GPIO.HIGH)

# ------------ Tkinter App ------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CJA Skyfarms Dashboard (Tkinter)")
        self.geometry("1000x700")

        # Keep track of GPIO states
        self.minifan_state = tk.BooleanVar(value=False)
        self.circ_state    = tk.BooleanVar(value=False)

        # For sensor values
        self.temp_var = tk.StringVar(value="-- °C")
        self.humi_var = tk.StringVar(value="-- %")
        self.ec_var   = tk.StringVar(value="-- dS/m")
        self.ph_var   = tk.StringVar(value="--")

        # For solution input
        self.sol_a_ml = tk.StringVar(value="")
        self.sol_b_ml = tk.StringVar(value="")
        self.sol_acid_ml = tk.StringVar(value="")
        self.last_inject_label = tk.StringVar(value="Last injection: -")

        self._build_ui()

        # Start periodic sensor updates
        self.update_temp_humi()
        self.update_ec_ph()

    # ---------- UI building ----------

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        frame_dashboard = ttk.Frame(notebook)
        frame_logs      = ttk.Frame(notebook)

        notebook.add(frame_dashboard, text="Dashboard")
        notebook.add(frame_logs, text="Logs")

        self._build_dashboard(frame_dashboard)
        self._build_logs(frame_logs)

    def _build_dashboard(self, parent):
        # Split into left/right frames
        left = ttk.Frame(parent)
        right = ttk.Frame(parent)
        left.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        right.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        # ---- Left: sensors ----
        group_temp = ttk.LabelFrame(left, text="Temperature & Humidity")
        group_temp.pack(fill="x", padx=5, pady=5)

        row1 = ttk.Frame(group_temp)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="Temperature:").pack(side="left")
        ttk.Label(row1, textvariable=self.temp_var, width=10).pack(side="left", padx=5)

        row2 = ttk.Frame(group_temp)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Humidity:").pack(side="left")
        ttk.Label(row2, textvariable=self.humi_var, width=10).pack(side="left", padx=5)

        ttk.Button(group_temp, text="Refresh now", command=self.update_temp_humi_once).pack(pady=5)

        group_ecph = ttk.LabelFrame(left, text="EC & pH")
        group_ecph.pack(fill="x", padx=5, pady=5)

        row3 = ttk.Frame(group_ecph)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="EC:").pack(side="left")
        ttk.Label(row3, textvariable=self.ec_var, width=10).pack(side="left", padx=5)

        row4 = ttk.Frame(group_ecph)
        row4.pack(fill="x", pady=2)
        ttk.Label(row4, text="pH:").pack(side="left")
        ttk.Label(row4, textvariable=self.ph_var, width=10).pack(side="left", padx=5)

        ttk.Button(group_ecph, text="Refresh now", command=self.update_ec_ph_once).pack(pady=5)

        # ---- Right: controller + solution ----
        group_ctrl = ttk.LabelFrame(right, text="Air conditioning / Controllers")
        group_ctrl.pack(fill="x", padx=5, pady=5)

        cb1 = ttk.Checkbutton(
            group_ctrl,
            text="Mini Fan (GPIO13)",
            variable=self.minifan_state,
            command=self.on_minifan_toggle
        )
        cb1.pack(anchor="w", pady=2)

        cb2 = ttk.Checkbutton(
            group_ctrl,
            text="Circulator (GPIO16)",
            variable=self.circ_state,
            command=self.on_circ_toggle
        )
        cb2.pack(anchor="w", pady=2)

        group_sol = ttk.LabelFrame(right, text="Inject Solution A, B, Acid")
        group_sol.pack(fill="x", padx=5, pady=10)

        # Solution A
        row_a = ttk.Frame(group_sol)
        row_a.pack(fill="x", pady=2)
        ttk.Label(row_a, text="Solution A (ml):").pack(side="left")
        ttk.Entry(row_a, textvariable=self.sol_a_ml, width=8).pack(side="left", padx=3)
        ttk.Button(row_a, text="Inject", command=lambda: self.inject_solution_from_ui("AB", self.sol_a_ml)).pack(side="left", padx=3)

        # Solution B
        row_b = ttk.Frame(group_sol)
        row_b.pack(fill="x", pady=2)
        ttk.Label(row_b, text="Solution B (ml):").pack(side="left")
        ttk.Entry(row_b, textvariable=self.sol_b_ml, width=8).pack(side="left", padx=3)
        ttk.Button(row_b, text="Inject", command=lambda: self.inject_solution_from_ui("B", self.sol_b_ml)).pack(side="left", padx=3)

        # Acid
        row_acid = ttk.Frame(group_sol)
        row_acid.pack(fill="x", pady=2)
        ttk.Label(row_acid, text="Acid (ml):").pack(side="left")
        ttk.Entry(row_acid, textvariable=self.sol_acid_ml, width=8).pack(side="left", padx=3)
        ttk.Button(row_acid, text="Inject", command=lambda: self.inject_solution_from_ui("Acid", self.sol_acid_ml)).pack(side="left", padx=3)

        ttk.Label(group_sol, textvariable=self.last_inject_label).pack(anchor="w", pady=5)

    def _build_logs(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=10, pady=5)
        ttk.Button(top, text="Reload Solution_input_log.csv", command=self.reload_log_view).pack(side="left")
        ttk.Label(top, text="(last 200 lines)").pack(side="left", padx=10)

        self.log_text = tk.Text(parent, wrap="none", height=30)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=5)

        self.reload_log_view()

    # ---------- GPIO handlers ----------

    def on_minifan_toggle(self):
        state = self.minifan_state.get()
        GPIO.output(PIN_MINIFAN, GPIO.LOW if state else GPIO.HIGH)

    def on_circ_toggle(self):
        state = self.circ_state.get()
        GPIO.output(PIN_CIRC, GPIO.LOW if state else GPIO.HIGH)

    # ---------- Sensor update ----------

    def update_temp_humi(self):
        self.update_temp_humi_once()
        # repeat every 20 minutes (1200 s)
        self.after(1200 * 1000, self.update_temp_humi)

    def update_temp_humi_once(self):
        line, err = run_python_script(TEMP_HUMI_SCRIPT)
        if err or not line:
            self.temp_var.set("Err")
            self.humi_var.set("Err")
            return
        try:
            data = json.loads(line)
            t = data.get("temperature")
            h = data.get("humidity")
            if t is not None:
                self.temp_var.set(f"{t:.1f} °C")
            if h is not None:
                self.humi_var.set(f"{h:.1f} %")
        except Exception:
            self.temp_var.set("ParseErr")
            self.humi_var.set("ParseErr")

    def update_ec_ph(self):
        self.update_ec_ph_once()
        # repeat every 5 minutes (예: 300s, 필요에 맞게 조정)
        self.after(300 * 1000, self.update_ec_ph)

    def update_ec_ph_once(self):
        line, err = run_python_script(EC_PH_SCRIPT)
        if err or not line:
            self.ec_var.set("Err")
            self.ph_var.set("Err")
            return
        try:
            data = json.loads(line)
            ec = data.get("EC")
            ph = data.get("pH")
            if ec is not None:
                self.ec_var.set(f"{float(ec):.2f} dS/m")
            if ph is not None:
                self.ph_var.set(f"{float(ph):.2f}")
        except Exception:
            self.ec_var.set("ParseErr")
            self.ph_var.set("ParseErr")

    # ---------- Solution injection ----------

    def inject_solution_from_ui(self, sol_name, var):
        text = var.get().strip()
        try:
            ml = float(text)
            if ml <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Input error", f"Invalid volume for {sol_name}: {text}")
            return

        ml_per_sec = 1.65
        duration_sec = ml / ml_per_sec

        # Log and update UI
        log_solution(sol_name, ml)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_inject_label.set(f"Last injection: {ts} ({sol_name} {ml:.1f} ml)")

        # Run pump in background thread
        th = threading.Thread(target=run_pump_blocking, args=(duration_sec,), daemon=True)
        th.start()

    # ---------- Logs tab ----------

    def reload_log_view(self):
        self.log_text.delete("1.0", "end")
        if not os.path.exists(SOLUTION_LOG_CSV):
            self.log_text.insert("end", f"{SOLUTION_LOG_CSV} not found.\n")
            return
        try:
            with open(SOLUTION_LOG_CSV, "r") as f:
                lines = f.readlines()
            tail = lines[-200:] if len(lines) > 200 else lines
            self.log_text.insert("end", "".join(tail))
        except Exception as e:
            self.log_text.insert("end", f"Error reading log: {e}\n")

    # ---------- Cleanup ----------

    def on_close(self):
        try:
            GPIO.cleanup()
        except Exception:
            pass
        self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
