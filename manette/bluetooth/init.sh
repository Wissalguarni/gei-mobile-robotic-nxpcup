#!/bin/sh

MAC="90:89:5F:F1:91:EB"

# 1. Charger le pilote NXP (sans effet s'il est déjà chargé) et attendre hci0
modprobe btnxpuart
i=0
while ! btmgmt info 2>/dev/null | grep -q "hci0:"; do
    sleep 0.5
    i=$((i + 1))
    if [ "$i" -ge 20 ]; then
        echo "ERREUR : hci0 introuvable après 10 s."
        exit 1
    fi
done

# 2. Passer le thread IRQ de l'UART Bluetooth en priorité temps réel haute (85)
UART_DEV=$(readlink -f /sys/class/bluetooth/hci0/device | sed -n 's|.*/\([0-9a-f]*\.serial\)/.*|\1|p')
IRQ_PID=$(ps -eo pid,comm | grep "irq/.*-$UART_DEV" | awk '{print $1}')
if [ -n "$IRQ_PID" ]; then
    chrt -f -p 85 "$IRQ_PID"
    echo "Priorité RT 85 appliquée sur $UART_DEV (PID $IRQ_PID)"
fi

# 3. Redémarrer BlueZ (applique --noplugin=input via zzz-no-input.conf)
systemctl daemon-reload
systemctl restart bluetooth
sleep 2
ps -ef | grep "[b]luetoothd"

# 4. Allumer la puce et optimiser la réception de connexion DS4
btmgmt power on
hciconfig hci0 lp ""
btmgmt connectable on
btmgmt fast-conn on