MAC="90:89:5F:F1:91:EB"

modprobe btnxpuart

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