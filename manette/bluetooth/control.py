#!/usr/bin/env python3
"""joy.py - Pilotage de la carte MCXA153 (I2C) via manette PS4 DualShock 4 (L2CAP brut).

Pré-requis :
- bluetoothd démarré avec --noplugin=input, manette déjà appairée, carte connectable
- mcx_i2c.py dans le même répertoire (ou dans PYTHONPATH) et module smbus2 installé
- script lancé en root (les PSM L2CAP 0x11 et 0x13 sont protégés)
"""
import ctypes
import errno
import os
import select
import socket
import struct
import sys
import time

from mcx_i2c import MCXBoard, MCXBoardError

# Configuration I2C (FRDM-IMX8MPLUS : /dev/i2c-2 par défaut)
I2C_BUS = 2
STICK_DEADZONE = 6        # zone morte autour de 128 (~5 %) pour éviter le tremblement servo
TRIGGER_DEADZONE = 3      # seuil minimal R2 avant démarrage moteurs
CMD_PERIOD = 0.04         # envoi I2C max toutes les 20 ms (50 Hz)

# Configuration Bluetooth L2CAP
PSM_CTRL = 0x11           # HID control
PSM_INTR = 0x13           # HID interrupt (données)
FAILSAFE_S = 0.2          # sans trame pendant 200 ms -> fail-safe
DISPLAY_PERIOD = 0.05     # affichage terminal 20 fois par seconde max

AF_BLUETOOTH = 31
BTPROTO_L2CAP = 0
SOL_BLUETOOTH = 274
BT_SECURITY = 4
BT_SECURITY_LOW = 1

DPAD = ("Haut", "Haut-Droite", "Droite", "Bas-Droite",
        "Bas", "Bas-Gauche", "Gauche", "Haut-Gauche")
BTN_1 = ((0x10, "Carre"), (0x20, "Croix"), (0x40, "Rond"), (0x80, "Triangle"))
BTN_2 = ((0x01, "L1"), (0x02, "R1"), (0x04, "L2"), (0x08, "R2"),
         (0x10, "Share"), (0x20, "Options"), (0x40, "L3"), (0x80, "R3"))
BTN_3 = ((0x01, "PS"), (0x02, "Pave-tactile"))

HINTS = {
    errno.EACCES: "Lance le script en root.",
    errno.EPERM: "Lance le script en root.",
    errno.EADDRINUSE: "Ce PSM est déjà utilisé (plugin input de bluetoothd, hidp...). "
                      "Démarre bluetoothd avec --noplugin=input puis relance.",
    errno.EAFNOSUPPORT: "Le noyau n'a pas le support Bluetooth/L2CAP (CONFIG_BT, CONFIG_BT_BREDR).",
    errno.EPROTONOSUPPORT: "Le noyau n'a pas le support L2CAP (CONFIG_BT_BREDR).",
}

libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.socket.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
libc.socket.restype = ctypes.c_int
libc.bind.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
libc.bind.restype = ctypes.c_int
libc.listen.argtypes = [ctypes.c_int, ctypes.c_int]
libc.listen.restype = ctypes.c_int
libc.accept.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
libc.accept.restype = ctypes.c_int
libc.setsockopt.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_void_p, ctypes.c_uint32]
libc.setsockopt.restype = ctypes.c_int


def fail(what):
    err = ctypes.get_errno()
    raise OSError(err, f"{what}: {os.strerror(err)}")


def listen_l2cap(psm):
    """Ouvre un socket L2CAP en écoute sur le PSM donné (root requis)."""
    fd = libc.socket(AF_BLUETOOTH, socket.SOCK_SEQPACKET, BTPROTO_L2CAP)
    if fd < 0:
        fail("socket L2CAP")
    sec = struct.pack("<BB", BT_SECURITY_LOW, 0)
    libc.setsockopt(fd, SOL_BLUETOOTH, BT_SECURITY, sec, len(sec))
    addr = struct.pack("<HH6sHBB", AF_BLUETOOTH, psm, b"\x00" * 6, 0, 0, 0)
    if libc.bind(fd, addr, len(addr)) < 0:
        err = ctypes.get_errno()
        os.close(fd)
        raise OSError(err, f"bind PSM 0x{psm:02x}: {os.strerror(err)}")
    if libc.listen(fd, 1) < 0:
        err = ctypes.get_errno()
        os.close(fd)
        raise OSError(err, f"listen PSM 0x{psm:02x}: {os.strerror(err)}")
    return fd


def close_quiet(fd):
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


def parse_report(data):
    """Décode une trame HID DS4 (préfixe 0xA1). Retourne un dict ou None."""
    if len(data) < 2 or data[0] != 0xA1:
        return None
    rid = data[1]
    if rid == 0x11 and len(data) >= 13:      # rapport étendu Bluetooth
        i = 4
    elif rid == 0x01 and len(data) >= 11:    # rapport simplifié Bluetooth
        i = 2
    else:
        return None
    b1, b2, b3 = data[i + 4], data[i + 5], data[i + 6]
    hat = b1 & 0x0F
    return {
        "report": rid,
        "lx": data[i], "ly": data[i + 1], "rx": data[i + 2], "ry": data[i + 3],
        "l2": data[i + 7], "r2": data[i + 8],
        "dpad": DPAD[hat] if hat < 8 else None,
        "buttons": ([n for m, n in BTN_1 if b1 & m]
                    + [n for m, n in BTN_2 if b2 & m]
                    + [n for m, n in BTN_3 if b3 & m]),
    }

MAX_SPEED_MOTOR = 70 # in 0-100
REACTIVITY_MOTOR = 25 # in % / sec
MAX_DIRECTION = 85 # in 0-100
OFFSET_DIRECTION = -5 # to shift the origin wheels alignement


def compute_controls(state):
    """Convertit l'état DS4 en consignes (puissance_moteurs 0..100, direction -100..100)."""
    # Gâchette R2 (0..255) -> puissance identique sur MOT1 et MOT2 (0..100 %)
    r2 = state["r2"]
    if r2 <= TRIGGER_DEADZONE:
        power = 0
    else:
        power = round((r2 / 255.0) * MAX_SPEED_MOTOR)
        power = max(0, min(100, power))

    # Joystick gauche horizontal lx (0..255, centre ~128) -> DIR (-100 gauche .. +100 droite)
    dx = state["lx"] - 128
    if abs(dx) <= STICK_DEADZONE:
        direction = 0
    else:
        direction = round((dx / 127.0) * MAX_DIRECTION) + OFFSET_DIRECTION
        direction = -max(-100, min(100, direction))

    return power, direction


def safe_stop(board):
    """Met immédiatement les moteurs et la direction au neutre."""
    try:
        board.set_motors_and_direction(0, 0, 0)
    except MCXBoardError as e:
        print(f"\n[ERREUR I2C] Échec mise en sécurité : {e}")


def format_state(s, power, direction):
    btn = " ".join(s["buttons"]) or "-"
    return (f"MOT:{power:3d}% | DIR:{direction:+4d} "
            f"(G_X:{s['lx']:3d} R2:{s['r2']:3d}) | {btn}")


def wait_connection(srv_ctrl, srv_intr):
    """Attend que la manette ouvre les deux canaux. Retourne (ctrl_fd, intr_fd)."""
    ctrl_fd = intr_fd = None
    waited = 0
    while ctrl_fd is None or intr_fd is None:
        watch = [s for s, c in ((srv_ctrl, ctrl_fd), (srv_intr, intr_fd)) if c is None]
        if ctrl_fd is not None:
            watch.append(ctrl_fd)
        readable, _, _ = select.select(watch, [], [], 5.0)
        if not readable:
            waited += 5
            print(f"  ... {waited} s : contrôle 0x11 "
                  f"{'ouvert' if ctrl_fd is not None else 'en attente'}, données 0x13 "
                  f"{'ouvert' if intr_fd is not None else 'en attente'}")
            continue
        for s in readable:
            if ctrl_fd is not None and s == ctrl_fd:
                try:
                    data = os.read(ctrl_fd, 128)
                except OSError:
                    data = b""
                if not data:
                    print("Canal contrôle fermé avant l'ouverture de 0x13 : la manette a abandonné.")
                    close_quiet(ctrl_fd)
                    ctrl_fd = None
                continue
            client = libc.accept(s, None, None)
            if client < 0:
                fail("accept")
            if s == srv_ctrl:
                ctrl_fd = client
                print("Canal contrôle (0x11) ouvert !")
            else:
                intr_fd = client
                print("Canal données (0x13) ouvert !")
    return ctrl_fd, intr_fd


def enable_extended_reports(ctrl_fd):
    """GET_REPORT(feature 0x02) : la DS4 passe alors aux rapports étendus 0x11."""
    try:
        os.write(ctrl_fd, b"\x43\x02")
        ready, _, _ = select.select([ctrl_fd], [], [], 1.0)
        if ready:
            os.read(ctrl_fd, 128)
    except OSError as e:
        print(f"Avertissement : activation des rapports étendus impossible ({e})")


def read_loop(ctrl_fd, intr_fd, board):
    """Lit la DS4 et pilote la carte MCX en continu. Retourne la raison de la sortie."""
    last_print = 0.0
    last_cmd_time = 0.0
    last_sent = (0, 0)
    first = True
    unknown = set()

    while True:
        readable, _, _ = select.select([intr_fd, ctrl_fd], [], [], FAILSAFE_S)
        if not readable:
            if last_sent != (0, 0):
                safe_stop(board)
                last_sent = (0, 0)
            print("\r[FAIL-SAFE] Aucune trame depuis 200 ms -> MOT = 0%, DIR = 0\x1b[K",
                  end="", flush=True)
            continue

        if ctrl_fd in readable:
            try:
                ctl = os.read(ctrl_fd, 128)
            except OSError:
                ctl = b""
            if not ctl:
                return "Canal de contrôle fermé"

        if intr_fd not in readable:
            continue

        try:
            data = os.read(intr_fd, 128)
        except OSError as e:
            if e.errno in (errno.ECONNRESET, errno.ENOTCONN, errno.EPIPE, errno.ECONNABORTED):
                return "Liaison coupée"
            raise
        if not data:
            return "Manette déconnectée"

        state = parse_report(data)
        if state is None:
            rid = data[1] if len(data) > 1 else -1
            if rid not in unknown:
                unknown.add(rid)
                print(f"\nTrame ignorée (type 0x{rid & 0xFF:02x}, {len(data)} octets) : "
                      f"{data[:16].hex(' ')}")
            continue

        if first:
            first = False
            print(f"\nPremière trame : rapport 0x{state['report']:02x}, {len(data)} octets")

        power, direction = compute_controls(state)
        now = time.monotonic()

        # Envoi I2C si les valeurs changent (immédiat si arrêt demandé, sinon max 50 Hz)
        cmd = (power, direction)
        interval_duration = now - last_cmd_time
        if cmd != last_sent and (cmd == (0, 0) or interval_duration >= CMD_PERIOD):
            try:
                (last_power, _) = last_sent
                if last_power < power:
                    power = last_power + min(REACTIVITY_MOTOR*interval_duration, power-last_power)
                else:
                    power = last_power - min(REACTIVITY_MOTOR*interval_duration, last_power-power)

                board.set_motors_and_direction(power, power, direction)
                last_sent = cmd
                last_cmd_time = now
            except MCXBoardError as e:
                print(f"\n[ERREUR I2C] {e}")

        if now - last_print >= DISPLAY_PERIOD:
            last_print = now
            print("\r" + format_state(state, power, direction) + "\x1b[K", end="", flush=True)


def main():
    if os.geteuid() != 0:
        sys.exit("Lance ce script en root (les PSM 0x11 et 0x13 sont protégés).")

    try:
        board = MCXBoard(bus=I2C_BUS)
    except MCXBoardError as e:
        sys.exit(f"ERREUR I2C au démarrage : {e}")

    with board:
        if board.is_board_present():
            print(f"Carte MCX détectée sur /dev/i2c-{I2C_BUS} : {board.get_status()}")
        else:
            print(f"Attention : carte MCX non détectée sur /dev/i2c-{I2C_BUS} (ID inattendu).")
        safe_stop(board)

        srv_ctrl = srv_intr = None
        try:
            srv_ctrl = listen_l2cap(PSM_CTRL)
            srv_intr = listen_l2cap(PSM_INTR)
        except OSError as e:
            print(f"ERREUR Bluetooth : {e}")
            if e.errno in HINTS:
                print(f"  -> {HINTS[e.errno]}")
            close_quiet(srv_ctrl)
            sys.exit(1)

        print("En écoute sur PSM 0x11 et 0x13. Appuie UNE FOIS sur le bouton PS (Ctrl+C pour quitter).")
        try:
            while True:
                ctrl_fd, intr_fd = wait_connection(srv_ctrl, srv_intr)
                try:
                    enable_extended_reports(ctrl_fd)
                    print("Manette connectée !")
                    reason = read_loop(ctrl_fd, intr_fd, board)
                finally:
                    safe_stop(board)
                    close_quiet(intr_fd)
                    close_quiet(ctrl_fd)
                print(f"\n[FAIL-SAFE] {reason} -> Moteurs arrêtés. "
                      "En attente d'une nouvelle connexion (appuie sur PS)...")
        except KeyboardInterrupt:
            print("\nArrêt demandé.")
        finally:
            safe_stop(board)
            close_quiet(srv_intr)
            close_quiet(srv_ctrl)


if __name__ == "__main__":
    main()
