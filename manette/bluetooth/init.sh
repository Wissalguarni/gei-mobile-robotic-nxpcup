MAC="90:89:5F:F1:91:EB"

modprobe btnxpuart

mount | grep -q debugfs || mount -t debugfs none /sys/kernel/debug
echo 0 > /sys/kernel/debug/bluetooth/hci0/min_encrypt_key_size

systemctl daemon-reload

systemctl restart bluetooth

ps -ef | grep bluetoothd


sleep 2

btmgmt pairable on

bluetoothctl << EOF
agent on
default-agent
quit
EOF

btmgmt connectable on 
btmgmt fast-conn on