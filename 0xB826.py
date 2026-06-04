import queue
import os
import threading
import struct
import time
from core.hdlc import hdlc_unescape, crc16
from core.modem import ModemClient

#setprop sys.usb.config diag,adb
class Inspector:
    def __init__(self, port):
        self.port = port
        self.packet_queue = queue.Queue()
        self.modem = ModemClient(port, logger=lambda x: None)
        self.running = True
        self.filename = "0xB826_COMBINED"
        self.unique_counter = 0
        self.output_file = open(self.filename, "a", buffering=1)

    def start(self):
        print(f"[*] Connecting to {self.port}...", end="", flush=True)

        try:
            self.modem.connect_and_subscribe([0x0826])
            print(" Success!")
        except Exception as e:
            print(" Failed!")
            print(f"[!] Could not connect to {self.port}")
            print("[!] Make sure that:")
            print("    - The DIAG port exists")
            print("    - QXDM or another script is not using it")
            print(f"\n[!] ERROR: {e}")

            self.output_file.close()
            return

        print("\n[*] Instructions:")
        print("    - Toggle airplane mode or switch between 4G<>5G to capture more fragments")
        print("    - Repeat a few times incase some fragments were missed")
        print("    - Press Ctrl + C to stop and save\n")

        print("\r[*] 0xB826 fragments found: 0", end="", flush=True)

        threading.Thread(
            target=self.modem.read_loop,
            args=(self.packet_queue,),
            daemon=True
        ).start()

        threading.Thread(
            target=self._worker_loop,
            daemon=True
        ).start()

        try:
            while True:
                time.sleep(0.2)

        except KeyboardInterrupt:
            print("\n\n[*] Stopping...")

        finally:
            self.stop()

    def stop(self):
        if not self.running:
            return

        self.running = False
        self.modem.disconnect()
        self.output_file.close()

        total = self._deduplicate_output()
        save_path = os.path.abspath(self.filename)

        print(f"[*] All done! total 0xB826 fragments: {total}")
        print(f"[*] Saved at -> {save_path}")

    def _deduplicate_output(self):
        print("[*] Removing duplicates...")

        if not os.path.exists(self.filename):
            return 0

        with open(self.filename, "r") as f:
            unique_lines = list(
                dict.fromkeys(line.strip() for line in f if line.strip())
            )

        with open(self.filename, "w") as f:
            f.write("\n".join(unique_lines) + "\n")

        print("[*] Saving...")
        return len(unique_lines)

    def _worker_loop(self):
        while self.running:
            try:
                self._process_packet(self.packet_queue.get(timeout=0.1))
            except queue.Empty:
                continue

    def _process_packet(self, packet):
        pkt = hdlc_unescape(packet)

        if len(pkt) < 18 or crc16(pkt[:-2]) != ((pkt[-1] << 8) | pkt[-2]):
            return

        clean_pkt = pkt[:-2]

        if clean_pkt[0] == 0x98 and len(clean_pkt) >= 8:
            clean_pkt = clean_pkt[8:]

        if len(clean_pkt) < 16 or clean_pkt[0] != 0x10:
            return

        if struct.unpack("<BBHHHQ", clean_pkt[:16])[4] != 0xB826:
            return

        payload = clean_pkt[16:]

        if not payload:
            return

        self.output_file.write(
            f"NR UE CA Combos Raw: {payload.hex()}\n"
        )

        self.unique_counter += 1
        print(
            f"\r[*] 0xB826 fragments found: {self.unique_counter}",
            end="",
            flush=True
        )


if __name__ == "__main__":
    port = input("Enter COM port (e.g. COM8, /dev/ttyUSB0): ").strip().upper()

    if not port:
        print("[!] No COM port entered.")
    else:
        Inspector(port).start()