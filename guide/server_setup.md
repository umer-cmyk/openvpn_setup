## 1.1 Install vnstat for Network Monitoring

Install and enable vnstat for network traffic statistics:

```bash
sudo apt install vnstat
sudo systemctl enable --now vnstat
```

*/3 * * * * /root/scripts/ovpn_monitor.py

