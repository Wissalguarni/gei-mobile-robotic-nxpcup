#!/usr/bin/env python3
"""joy.py - Lecture d'une manette PS4 DualShock 4 en Bluetooth (L2CAP brut).

Pré-requis : bluetoothd démarré, manette déjà appairée, carte connectable,
script lancé en root (voir la procédure).

Le script écoute sur les PSM HID 0x11 (contrôle) et 0x13 (données), attend
que la manette se connecte (appui sur PS), puis affiche en continu les
sticks, gâchettes, croix directionnelle et boutons. Si la manette se
déconnecte ou n'envoie plus rien, il l'indique (fail-safe) et se remet en
attente d'une nouvelle connexion.
"""
import ctypes
import errno
import os
import select
import socket
import struct
import sys
import time

PSM_CTRL = 0x11           # HID control
PSM_INTR = 0x13           # HID interrupt (données)
FAILSAFE_S = 0.2          # sans trame pendant 200 ms -> fail-safe
DISPLAY_PERIOD = 0.05     # affichage 20 fois par seconde au maximum

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
    # Pas d'exigence de chiffrement côté socket : l'authentification est
    # gérée par bluetoothd avec la clé enregistrée.
    sec = struct.pack("<BB", BT_SECURITY_LOW, 0)
    libc.setsockopt(fd, SOL_BLUETOOTH, BT_SECURITY, sec, len(sec))
    # sockaddr_l2 : family, psm, bdaddr, cid, bdaddr_type, pad
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


def format_state(s):
    def norm(v):
        return max(-1.0, min(1.0, (v - 128) / 127.0))
    btn = " ".join(s["buttons"]) or "-"
    return (f"G({norm(s['lx']):+.2f},{norm(s['ly']):+.2f}) "
            f"D({norm(s['rx']):+.2f},{norm(s['ry']):+.2f}) "
            f"L2:{s['l2'] / 255:.2f} R2:{s['r2'] / 255:.2f} "
            f"Dpad:{s['dpad'] or '-'} | {btn}")


def wait_connection(srv_ctrl, srv_intr):
    """Attend que la manette ouvre les deux canaux. Retourne (ctrl_fd, intr_fd)."""
    ctrl_fd = intr_fd = None
    waited = 0
    while ctrl_fd is None or intr_fd is None:
        watch = [s for s, c in ((srv_ctrl, ctrl_fd), (srv_intr, intr_fd)) if c is None]
        if ctrl_fd is not None:
            watch.append(ctrl_fd)     # détecte un abandon avant l'ouverture de 0x13
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


def read_loop(ctrl_fd, intr_fd):
    """Affiche l'état en continu. Retourne la raison de la sortie."""
    last_print = 0.0
    first = True
    unknown = set()
    while True:
        readable, _, _ = select.select([intr_fd, ctrl_fd], [], [], FAILSAFE_S)
        if not readable:
            print("\r[FAIL-SAFE] Aucune trame depuis 200 ms -> Gaz = 0, Frein actif !\x1b[K",
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
        now = time.monotonic()
        if now - last_print >= DISPLAY_PERIOD:
            last_print = now
            print("\r" + format_state(state) + "\x1b[K", end="", flush=True)


def main():
    if os.geteuid() != 0:
        sys.exit("Lance ce script en root (les PSM 0x11 et 0x13 sont protégés).")
    srv_ctrl = srv_intr = None
    try:
        srv_ctrl = listen_l2cap(PSM_CTRL)
        srv_intr = listen_l2cap(PSM_INTR)
    except OSError as e:
        print(f"ERREUR : {e}")
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
                reason = read_loop(ctrl_fd, intr_fd)
                print(f"\n[FAIL-SAFE] {reason} -> Gaz = 0, Frein actif. "
                      "En attente d'une nouvelle connexion (appuie sur PS)...")
            finally:
                close_quiet(intr_fd)
                close_quiet(ctrl_fd)
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        close_quiet(srv_intr)
        close_quiet(srv_ctrl)


if __name__ == "__main__":
    main()
