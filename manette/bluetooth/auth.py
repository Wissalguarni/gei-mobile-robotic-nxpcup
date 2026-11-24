import ctypes, fcntl, glob, os, re, subprocess

class UsbCtrlTransfer(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_uint8),
        ("bRequest", ctypes.c_uint8),
        ("wValue", ctypes.c_uint16),
        ("wIndex", ctypes.c_uint16),
        ("wLength", ctypes.c_uint16),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]

class UsbIoctl(ctypes.Structure):
    _fields_ = [
        ("ifno", ctypes.c_int),
        ("ioctl_code", ctypes.c_int),
        ("data", ctypes.c_void_p),
    ]

out = subprocess.check_output(["bluetoothctl", "list"], text=True)
host_mac = re.search(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})", out).group(1).upper()

usb_dev = None
for dev in glob.glob("/sys/bus/usb/devices/*"):
    vid_f = os.path.join(dev, "idVendor")
    if os.path.exists(vid_f) and open(vid_f).read().strip().lower() == "054c":
        bus = int(open(os.path.join(dev, "busnum")).read())
        num = int(open(os.path.join(dev, "devnum")).read())
        usb_dev = f"/dev/bus/usb/{bus:03d}/{num:03d}"
        break

if not usb_dev:
    raise RuntimeError("Manette Sony (054c) non trouvée sur /dev/bus/usb.")

link_key = os.urandom(16)
buf = (ctypes.c_ubyte * 23)()
buf[0] = 0x13
for i, b in enumerate(reversed(host_mac.split(":"))):
    buf[1 + i] = int(b, 16)
for i, b in enumerate(link_key):
    buf[7 + i] = b

fd = os.open(usb_dev, os.O_RDWR)
try:
    # Détache le pilote noyau HID sur l'interface 0 (USBDEVFS_IOCTL + USBDEVFS_DISCONNECT)
    disconn = UsbIoctl(0, 0x5516, None)
    fcntl.ioctl(fd, 0xC0105512, disconn)
except OSError:
    pass

ctrl = UsbCtrlTransfer(0x21, 0x09, 0x0313, 0, 23, 1000, ctypes.addressof(buf))
fcntl.ioctl(fd, 0xC0185500, ctrl)
os.close(fd)

info_dir = f"/var/lib/bluetooth/{host_mac}/90:89:5F:F1:91:EB"
os.makedirs(info_dir, exist_ok=True)
key_hex = link_key.hex().upper()
with open(f"{info_dir}/info", "w") as f:
    f.write(f"[General]\nName=Wireless Controller\nTrusted=true\n\n[LinkKey]\nKey={key_hex}\nType=4\nPINLength=0\n")

subprocess.run(["systemctl", "restart", "bluetooth"], check=True)
subprocess.run(["hciconfig", "hci0", "up"], check=False)
subprocess.run(["bluetoothctl", "power", "on"], check=True)
print(f"OK : Clé enregistrée via {usb_dev} pour l'hôte {host_mac} (clé {key_hex})")
