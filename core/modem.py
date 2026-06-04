import serial
import struct
import time
from core.hdlc import hdlc_escape

KNOWN_TEXT_SUBSYSTEMS = [
    (0x0000, 0x00c8), (0x01f4, 0x02bc), (0x03e8, 0x04b0), (0x07d0, 0x0898),
    (0x0bb8, 0x0c80), (0x0fa0, 0x1068), (0x1194, 0x12c0), (0x1388, 0x1450),
    (0x157c, 0x1644), (0x1770, 0x1838), (0x1964, 0x1a2c), (0x1b58, 0x1ce8),
    (0x1f40, 0x2008), (0x2134, 0x21fc), (0x2328, 0x23f0), (0x251c, 0x25e4),
    (0x27d8, 0x2968)
]

class ModemClient:
    def __init__(self, port, baud=115200, logger=None):
        self.port = port
        self.baud = baud
        self.ser = None
        self.running = False
        self.logger = logger or (lambda x: None)

    def write_cmd(self, cmd, sub_cmd=None, payload=b''):
        hdr = struct.pack('<BB', cmd, sub_cmd) if sub_cmd else struct.pack('<B', cmd)
        self.ser.write(hdlc_escape(hdr + payload))

    def _build_log_mask(self, equip_id: int, last_item: int, items: list) -> bytes:
        header = struct.pack('<LLLL', 0x73, 3, equip_id, last_item)
        reqd_bytes = (last_item // 8) + 1 if last_item % 8 else last_item // 8
        payload = bytearray(b'\x00' * reqd_bytes)
        for bit in items:
            if bit <= last_item: payload[bit // 8] |= (1 << (bit % 8))
        return hdlc_escape(header + bytes(payload))

    def connect_and_subscribe(self, log_ids):
        self.logger(f"Opening port {self.port}...")
        self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
        self.ser.dtr = False; time.sleep(0.1); self.ser.dtr = True; time.sleep(0.1)

        self.logger("Waking up modem...")
        self.write_cmd(0x00) 
        time.sleep(0.2)

        self.logger("Silencing irrelevant logs...")
        self.write_cmd(0x60, 0x00) 
        self.ser.write(hdlc_escape(struct.pack('<LL', 0x73, 0)))
        for start, end in KNOWN_TEXT_SUBSYSTEMS:
            self.write_cmd(0x7D, 0x04, struct.pack('<HHH', start, end, 0) + (b'\x00\x00\x00\x00' * (end - start + 1)))
        
        self.logger("Subscribing to target LOG ID(s)...")
        self.ser.write(self._build_log_mask(0x0B, 0x09FF, log_ids))
        self.write_cmd(0x60, 0x01)
        self.logger("Subscribed to LOG ID(s). Listening.")

    def read_loop(self, packet_queue):
        self.running = True
        oldbuf = b''
        while self.running:
            buf = self.ser.read(4096)
            if not buf: continue
            
            buf = oldbuf + buf
            packets = buf.split(b'\x7e')

            if len(buf) < 1 or buf[-1] != 0x7e:
                oldbuf = packets.pop()
            else:
                oldbuf = b''

            for pkt in packets:
                if len(pkt) > 0:
                    packet_queue.put(pkt)
                    
    def disconnect(self):
        self.running = False
        if self.ser: self.ser.close()