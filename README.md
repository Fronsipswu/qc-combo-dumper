# Qualcomm Hardware CA Combos Dumper

A simple Python-based tool to dump LTE Support CA Combos (0xB0CD) and NR5G Supported CA Combos (0xB826) from any qualcomm devices via the DIAG port. Each fragments contains a maximum of 100 Combos. To obtain all combos, the script combines multiple fragments into a single output and removes any duplicates before dumping them into your working directory.

---

## Supported devices

- Any Qualcomm devices as long as you can open the DIAG port
- LTE 0xB0CD dump should work on all Qualcomm devices
- NR5G 0xB826 dump is **not supported** for X80 modems or newer

To enable DIAG on most rooted Androids:

```bash
su
setprop sys.usb.config diag,adb
```

## PC Requirements

- Qualcomm USB Drivers installed
- Ensure QXDM, QPST, or other DIAG tools are closed
- Pyserial (except for those who use the one-file .exe)

---

# Usage

## Standalone .exe (Windows only)
1. Go to the **Releases** page
2. Download ```qc-combo-dumper.exe``` from the release section
3. Run the executable
4. Connect your Qualcomm device to your computer and make sure DIAG is enabled
5. Select your DIAG port from the drop-down menu (You can find the COM port in Device manager)
6. Select capture mode e.g LTE (0xB0CD) or NR5G (0xB826)
7. Click **Connect** and follow the on-screen instructions
8. Press stop to dump the output

The output will be saved as ```0xB0CD_COMBINED``` or ```0xB826_COMBINED``` in wherever the .exe is

<img width="600" height="466" alt="image" src="https://github.com/user-attachments/assets/cf1a531b-a816-4e3e-a520-0c943e7c7479" />


## Run Python Script Directly

Clone the repository:

```bash
git clone https://github.com/Fronsipswu/qc-combo-dumper.git
cd qc-combo-dumper
```
Install Pyserial if you do not have it:

```
pip install pyserial
```
Start script for LTE dumping
```
python 0xB0CD.py
```
For NR
```
python 0xB826.py
```
You will be asked to manually specify the DIAG port in the terminal. e.g. ```COM8``` on windows or ```/dev/ttyUSB0``` on Linux. From here, just follow the on-screen instructions and the output should be saved in the same directory as the .py script

# Output

NR5G Supported CA Combos:
```text
NR UE CA Combos Raw: 0d000000170a00...
NR UE CA Combos Raw: 0d000000170a64...
NR UE CA Combos Raw: 0d000000170ac8...
```
LTE Supported CA Combos:

```text
LTE UE CA Combos Raw: 2964044700...
LTE UE CA Combos Raw: 2964044200...
LTE UE CA Combos Raw: 2964034200...
```

# Credits
All core functionalities in this project such as DIAG initialization, HDLC unescaping, and CRC16 handling, were reused/adapted from the [scat](https://github.com/fgsect/scat) repository. Credit goes to the original authors and contributors for their work on DIAG protocol tooling and analysis.
