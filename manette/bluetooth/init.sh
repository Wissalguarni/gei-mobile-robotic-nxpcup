MAC="90:89:5F:F1:91:EB"

modprobe btnxpuart

systemctl daemon-reload

systemctl restart bluetooth

ps -ef | grep bluetoothd


sleep 2

btmgmt pairable on
bluetoothctl --timeout 8 scan on

bluetoothctl << EOF
agent on
default-agent
pair $MAC
trust $MAC
quit
EOF

btmgmt connectable on 
