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
        
        self.running, self._stopped = True, False
        self.filename, self.saved_count = "0xB0CD_COMBINED", 0
        self.output_file = open(self.filename, "a", buffering=1)
        
        self.burst_fragments = []
        self.last_b0cd_time = time.time()

    def start(self):
        print(f"[*] 0xB0CD LTE hardware combo capture started -> Connecting to {self.port}...", end="", flush=True)

        try:
            self.modem.connect_and_subscribe([0x00CD])
            print(" Connected!")
        except Exception as e:
            print(f"\n[!] ERROR: Failed to connect to {self.port}.")
            print(f"[!] Please check if the port is correct, plugged in, and not used by QXDM/another script.")
            self.output_file.close()
            return

        print("\n[*] You might need to toggle airplane mode to get 0xB0CD fragments")

        print("\r[*] 0xB0CD fragments found: 0", end="", flush=True)

        threading.Thread(target=self.modem.read_loop, args=(self.packet_queue,), daemon=True).start()
        threading.Thread(target=self._worker_loop, daemon=True).start()

        try:
            while self.running:
                time.sleep(0.1)
                # Flush if there's a timeout
                if self.burst_fragments and time.time() - self.last_b0cd_time > 1:
                    self._flush_buffer()

        except KeyboardInterrupt:
            print("\n\n[*] Manual stop triggered...")
        finally:
            self.stop()

    def _flush_buffer(self):
        if not self.burst_fragments: return

        for fragment_hex in self.burst_fragments:
            self.output_file.write(f"LTE UE CA Combos Raw: {fragment_hex}\n")
            self.saved_count += 1
            
        self.output_file.flush()
        print(f"\r[*] 0xB0CD fragments found: {self.saved_count}", end="", flush=True)

        self.burst_fragments = []

        # Auto exit
        if self.saved_count > 0:
            self.running = False

    def stop(self):
        if self._stopped: return 
        self._stopped = True
        self.running = False

        if self.burst_fragments:
            self._flush_buffer()

        self.modem.disconnect()
        self.output_file.close()

        print()
        
        print(f"[*] All done! Fragments saved: {self.saved_count}")
        print(f"[*] Saved at -> {os.path.abspath(self.filename)}")

    def _worker_loop(self):
        while self.running:
            try: 
                self._process_packet(self.packet_queue.get(timeout=0.1))
            except queue.Empty: 
                continue

    def _process_packet(self, packet):
        pkt = hdlc_unescape(packet)
        if len(pkt) < 18 or crc16(pkt[:-2]) != ((pkt[-1] << 8) | pkt[-2]): return

        clean_pkt = pkt[:-2]
        clean_pkt = clean_pkt[8:] if clean_pkt[0] == 0x98 and len(clean_pkt) >= 8 else clean_pkt

        if len(clean_pkt) < 16 or clean_pkt[0] != 0x10: return
        if struct.unpack("<BBHHHQ", clean_pkt[:16])[4] != 0xB0CD: return

        payload = clean_pkt[16:]
        if not payload: return

        self.last_b0cd_time = time.time()
        self.burst_fragments.append(payload.hex())

        # Flush immediately if fragment end condition is met
        if len(payload) > 1 and payload[1] < 100:
            self._flush_buffer()

if __name__ == "__main__":
    port = input("Enter DIAG port (e.g. COM8, /dev/ttyUSB0): ").strip()
    if not port:
        print("[!] No port entered.")
    else:
        Inspector(port).start()