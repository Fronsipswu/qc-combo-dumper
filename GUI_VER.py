import os
import queue
import struct
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from serial.tools import list_ports
from core.hdlc import hdlc_unescape, crc16
from core.modem import ModemClient


LOG_SPECS = {
    "NR": {
        "label": "NR5G Supported CA Combos (0xB826)",
        "subscribe_id": 0x0826,
        "check_id": 0xB826,
        "filename": "0xB826_COMBINED",
        "prefix": "NR UE CA Combos Raw: ",
        "status_name": "0xB826",
    },
    "LTE": {
        "label": "LTE Supported CA Combos (0xB0CD)",
        "subscribe_id": 0x00CD,
        "check_id": 0xB0CD,
        "filename": "0xB0CD_COMBINED",
        "prefix": "LTE UE CA Combos Raw: ",
        "status_name": "0xB0CD",
    },
}


class ComboCaptureGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Qualcomm CA Combo Dumper")
        self.root.geometry("680x500")
        self.root.minsize(680, 500)

        self.port_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="NR")
        self.status_var = tk.StringVar(value="")
        self.connect_btn_var = tk.StringVar(value="Start")

        self.packet_queue = None
        self.modem = None
        self.output_file = None
        self.filename = None

        self.running = False
        self.connected = False
        
        # Shared capture variables
        self.saved_count = 0
        self.burst_fragments = []
        self.last_b0cd_time = 0

        self.read_thread = None
        self.work_thread = None

        self.log_queue = queue.Queue()

        self._build_ui()
        self._refresh_ports()
        self._schedule_port_refresh()
        self._poll_log_queue()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=(10, 10, 10, 6))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(6, weight=1)

        ttk.Label(top, text="DIAG Port").grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.port_combo = ttk.Combobox(
            top,
            textvariable=self.port_var,
            width=8,
            state="readonly",
            values=(),
        )
        self.port_combo.grid(row=0, column=1, padx=(0, 6), sticky="w")
        self.port_combo.bind("<Button-1>", lambda _e: self._refresh_ports())

        self.refresh_btn = ttk.Button(top, text="Refresh", command=self._refresh_ports)
        self.refresh_btn.grid(row=0, column=2, padx=(0, 14), sticky="w")

        mode_frame = ttk.LabelFrame(top, text="Select Capture", padding=(8, 4, 8, 4))
        mode_frame.grid(row=0, column=3, padx=(0, 14), sticky="w")

        ttk.Radiobutton(
            mode_frame,
            text="NR5G Supported CA Combos (0xB826)",
            variable=self.mode_var,
            value="NR",
        ).grid(row=0, column=0, sticky="w")

        ttk.Radiobutton(
            mode_frame,
            text="LTE Supported CA Combos (0xB0CD)",
            variable=self.mode_var,
            value="LTE",
        ).grid(row=1, column=0, sticky="w")

        self.connect_btn = ttk.Button(top, textvariable=self.connect_btn_var, command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=4, padx=(0, 12), sticky="w")

        ttk.Label(top, textvariable=self.status_var).grid(row=0, column=5, sticky="w")

        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom.grid(row=1, column=0, sticky="nsew")
        bottom.rowconfigure(0, weight=1)
        bottom.columnconfigure(0, weight=1)

        self.terminal = ScrolledText(
            bottom,
            wrap="word",
            height=20,
            state="disabled",
            font=("Consolas", 10),
        )
        self.terminal.grid(row=0, column=0, sticky="nsew")

    def _refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        ports.sort(key=self._port_sort_key)

        current = self.port_var.get().strip()
        self.port_combo["values"] = ports

        if current in ports:
            self.port_var.set(current)
        elif ports:
            self.port_var.set(ports[0])
        else:
            self.port_var.set("")

    def _schedule_port_refresh(self):
        if not self.connected:
            self._refresh_ports()
        self.root.after(3000, self._schedule_port_refresh)

    @staticmethod
    def _port_sort_key(port_name: str):
        upper = port_name.upper()
        if upper.startswith("COM"):
            try:
                return (0, int(upper[3:]))
            except ValueError:
                return (0, upper)
        return (1, upper)

    def _log(self, text: str, end: str = "\n", replace_last: bool = False):
        self.log_queue.put((text, end, replace_last))

    def _poll_log_queue(self):
        try:
            while True:
                msg, end_str, replace_last = self.log_queue.get_nowait()
                self.terminal.configure(state="normal")
                
                #\r behavior in tkinter
                if replace_last:
                    self.terminal.delete("end-2l linestart", "end-1c")
                    self.terminal.insert("end-1c", msg + "\n")
                else:
                    self.terminal.insert("end-1c", msg + end_str)
                    
                self.terminal.see("end")
                self.terminal.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(50, self._poll_log_queue)

    def toggle_connection(self):
        if self.connected:
            self.stop_capture()
        else:
            self.start_capture()

    def start_capture(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("No COM port", "Select a COM port first.")
            return

        mode = self.mode_var.get()
        spec = LOG_SPECS[mode]

        self.filename = spec["filename"]
        self.saved_count = 0
        self.burst_fragments = []
        self.last_b0cd_time = time.time()
        
        self.packet_queue = queue.Queue()
        self.modem = ModemClient(port, logger=lambda _x: None)
        self.running = True

        try:
            self.status_var.set(f"Connecting to {port}...")
            
            if mode == "LTE":
                self._log(f"[*] 0xB0CD LTE hardware combo capture started -> Connecting to {port}...", end="")
            else:
                self._log(f"[*] Connecting to {port}...", end="")

            self.modem.connect_and_subscribe([spec["subscribe_id"]])
            
            if mode == "LTE":
                self._log(" Connected!")
                self._log("\n[*] You might need to toggle airplane mode to get 0xB0CD fragments")
                self._log("\n[*] 0xB0CD fragments found: 0")
            else:
                self._log(" Success!")
                self._log("\n[*] Instructions:")
                self._log("    - Toggle airplane mode or switch between 4G<>5G to capture more fragments")
                self._log("    - Repeat a few times incase some fragments were missed")
                self._log("    - Click Stop to save\n")
                self._log("[*] 0xB826 fragments found: 0")

        except Exception as e:
            self.status_var.set("Idle")
            
            if mode == "LTE":
                self._log(f"\n[!] ERROR: Failed to connect to {port}.")
                self._log("[!] Please check if the port is correct, plugged in, and not used by QXDM/another script.")
            else:
                self._log(" Failed!")
                self._log(f"[!] Could not connect to {port}")
                self._log("[!] Make sure that:")
                self._log("    - The DIAG port exists")
                self._log("    - QXDM or another script is not using it")
                self._log(f"\n[!] ERROR: {e}")

            messagebox.showerror("Connection failed", "Could not connect. Check terminal for details.")
            self.modem = None
            self.running = False
            return

        try:
            self.output_file = open(self.filename, "a", buffering=1)
        except Exception as e:
            self._log(f"[!] Could not open output file {self.filename}: {e}")
            messagebox.showerror("File error", f"Could not open {self.filename}:\n{e}")
            self.modem.disconnect()
            self.modem = None
            self.running = False
            return

        self.connected = True
        self.connect_btn_var.set("Stop")
        self.status_var.set(f"Connected")

        self.read_thread = threading.Thread(
            target=self.modem.read_loop,
            args=(self.packet_queue,),
            daemon=True,
        )
        self.work_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
        )
        self.read_thread.start()
        self.work_thread.start()

        self._set_controls_enabled(False)

    def stop_capture(self):
        if not self.connected and not self.running:
            return

        self.running = False
        self.connected = False

        self._set_controls_enabled(True)
        self.connect_btn_var.set("Connect")
        self.status_var.set("Stopping...")
        
        if self.mode_var.get() == "LTE" and self.burst_fragments:
            self._flush_lte_buffer()

        try:
            if self.modem:
                self.modem.disconnect()
        except Exception:
            pass

        if self.work_thread and self.work_thread.is_alive():
            self.work_thread.join(timeout=1.0)

        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=1.0)

        try:
            if self.output_file:
                self.output_file.close()
        except Exception:
            pass

        self.output_file = None
        self.modem = None

        self._log("\n[*] Stopping...")

        if self.mode_var.get() == "NR":
            total = self._deduplicate_output(self.filename) if self.filename else 0
            self._log(f"[*] All done! total 0xB826 fragments: {total}")
            self.status_var.set(f"")
        else:
            total = self.saved_count
            self._log(f"[*] All done! Fragments saved: {total}")
            self.status_var.set(f"")

        if self.filename:
            self._log(f"[*] Saved at -> {os.path.abspath(self.filename)}\n")

    def _set_controls_enabled(self, enabled: bool):
            state = "normal" if enabled else "disabled"
            self.port_combo.configure(state="readonly" if enabled else "disabled")
            self.refresh_btn.configure(state=state)
            
            for widget in self.root.winfo_children():
                if isinstance(widget, ttk.Frame):
                    for sub in widget.winfo_children():
                        try:
                            if sub is not self.connect_btn:
                                sub.configure(state=state)
                        except tk.TclError:
                            pass

            if enabled:
                self.port_combo.configure(state="readonly")

    def _deduplicate_output(self, filename):
        self._log("\n[*] Removing duplicates...")

        if not filename or not os.path.exists(filename):
            return 0

        try:
            with open(filename, "r") as f:
                unique_lines = list(
                    dict.fromkeys(line.strip() for line in f if line.strip())
                )

            with open(filename, "w") as f:
                f.write("\n".join(unique_lines) + "\n")

            self._log("[*] Saving...")
            return len(unique_lines)
        except Exception as e:
            self._log(f"[!] Deduplication failed: {e}")
            return self.saved_count

    def _flush_lte_buffer(self):
        if not self.burst_fragments: return

        for fragment_hex in self.burst_fragments:
            line = f"LTE UE CA Combos Raw: {fragment_hex}"
            if self.output_file:
                self.output_file.write(line + "\n")
            self.saved_count += 1
            
        if self.output_file:
            self.output_file.flush()
            
        self._log(f"[*] 0xB0CD fragments found: {self.saved_count}", replace_last=True)
        self.burst_fragments = []

        if self.saved_count > 0 and self.running:
            self.root.after(0, self.stop_capture)

    def _worker_loop(self):
        while self.running:
            try:
                pkt = self.packet_queue.get(timeout=0.1)
                self._process_packet(pkt)
            except queue.Empty:
                pass
            except Exception as e:
                self._log(f"[!] Worker error: {e}")
                
            # Evaluated identically to the while-loop sleep check in 0xB0CD.py 
            if self.mode_var.get() == "LTE" and self.burst_fragments:
                if time.time() - self.last_b0cd_time > 1:
                    self._flush_lte_buffer()

    def _process_packet(self, packet):
            pkt = hdlc_unescape(packet)

            if len(pkt) < 18 or crc16(pkt[:-2]) != ((pkt[-1] << 8) | pkt[-2]):
                return

            clean_pkt = pkt[:-2]

            if clean_pkt[0] == 0x98 and len(clean_pkt) >= 8:
                clean_pkt = clean_pkt[8:]

            if len(clean_pkt) < 16 or clean_pkt[0] != 0x10:
                return

            mode = self.mode_var.get()
            spec = LOG_SPECS[mode]

            # Compare against the correct diagnostic header check_id, e.g. 0xB826
            if struct.unpack("<BBHHHQ", clean_pkt[:16])[4] != spec["check_id"]:
                return

            payload = clean_pkt[16:]

            if not payload:
                return

            if mode == "LTE":
                self.last_b0cd_time = time.time()
                self.burst_fragments.append(payload.hex())

                # Flush immediately if fragment end condition is met
                if len(payload) > 1 and payload[1] < 100:
                    self._flush_lte_buffer()
                    
            elif mode == "NR":
                self.output_file.write(f"NR UE CA Combos Raw: {payload.hex()}\n")
                self.saved_count += 1

                self._log(f"[*] 0xB826 fragments found: {self.saved_count}", replace_last=True)
                self.root.after(0, lambda: self.status_var.set(
                    f"Connected"
                ))

    def on_close(self):
        if self.connected or self.running:
            self.stop_capture()
        self.root.destroy()


def main():
    root = tk.Tk()

    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass

    app = ComboCaptureGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()