#!/usr/bin/env python3
import time
import subprocess
import requests
import os
import json

# ----------------------------
# CONFIGURATION
# ----------------------------
API_BASE_URL = "https://papi.fusionsai.net/api"
OVPN_INTERFACE = "tun0" # Default OpenVPN interface
STATUS_FILE = "/var/log/openvpn/openvpn-status.log" # Path to your OpenVPN status log
NETWORK_INTERFACE = "<interface>" # REPLACE with your actual WAN interface (e.g., eth0)
SERVICE_NAME = "openvpn-server@server.service" # Adjust if your service is named differently
PLATFORM = "android"

# ----------------------------
# FETCH PUBLIC IP
# ----------------------------
try:
    command = "curl -s -4 icanhazip.com"
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, text=True)
    ipAddress = result.stdout.strip()
    if not ipAddress:
        ipAddress = "0.0.0.0"
except Exception as e:
    print(f"[ERROR] Could not fetch IP: {e}")
    ipAddress = "0.0.0.0"

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------

def get_download_speed(interface, interval=1):
    """
    Calculates only Download (RX) speed in Mbps.
    """
    def get_rx_bytes(iface):
        try:
            return int(open(f'/sys/class/net/{iface}/statistics/rx_bytes').read())
        except FileNotFoundError:
            return 0

    rx1 = get_rx_bytes(interface)
    time.sleep(interval)
    rx2 = get_rx_bytes(interface)

    # Calculate Mbps: (Bytes * 8) / 1,000,000 / seconds
    download_mbps = round(((rx2 - rx1) * 8) / 1_000_000 / interval, 2)
    return download_mbps

def get_vnstat_usage(interface):
    stats = {"daily": 0.0, "weekly": 0.0, "monthly": 0.0}
    if subprocess.call(["which", "vnstat"], stdout=subprocess.DEVNULL) != 0:
        return stats

    try:
        result = subprocess.run(["vnstat", "-i", interface, "--json"], capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return stats

        data = json.loads(result.stdout)
        if "interfaces" not in data or not data["interfaces"]:
            return stats

        iface_data = data["interfaces"][0]
        traffic = iface_data.get("traffic", {})

        # Daily
        days = traffic.get("day", [])
        if days:
            today = days[-1]
            stats["daily"] = round((today['rx'] + today['tx']) / 1073741824, 2)

        # Weekly (Sum last 7 days)
        if days:
            last_7 = days[-7:]
            week_bytes = sum(d['rx'] + d['tx'] for d in last_7)
            stats["weekly"] = round(week_bytes / 1073741824, 2)

        # Monthly
        months = traffic.get("month", [])
        if months:
            this_month = months[-1]
            stats["monthly"] = round((this_month['rx'] + this_month['tx']) / 1073741824, 2)

        return stats
    except Exception:
        return stats

def get_ovpn_users():
    """
    Reads the OpenVPN status file using a custom shell command.
    """
    try:
        # Using your exact working shell command to count the connected clients
        command = "grep /var/log/openvpn/openvpn-status.log -e 'CLIENT_LIST,client,' | awk -F ',' '{print $3}' | wc -l"
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, text=True)
        
        active_clients = result.stdout.strip()
        
        # Return the count, or "0" if the command somehow returns empty
        return active_clients if active_clients else "0"
    except Exception as e:
        print(f"[ERROR] Failed to read OpenVPN users: {e}")
        return "0"

def get_cpu_usage_15min():
    try:
        load1, load5, load15 = os.getloadavg()
        total_cores = os.cpu_count() or 1
        return round((load15 / total_cores) * 100, 2)
    except Exception:
        return 0.0

def check_service_status(service_name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return "1" if result.stdout.strip() == "active" else "0"
    except Exception:
        return "0"

# ----------------------------
# MAIN LOGIC
# ----------------------------
def send_data():
    print(f"Getting stats for IP: {ipAddress}")
    
    # --- PHASE 1: GATHER DATA & PRINT STATS ---
    
    # 1. Users
    user_count = get_ovpn_users()
    print(f"Total OpenVPN Active Clients: {user_count}")

    # 2. CPU
    cpu_val = get_cpu_usage_15min()
    print(f"CPU Utilization (15m avg): {cpu_val}%")
    
    # 3. Service Status
    svc_status = check_service_status(SERVICE_NAME)
    print(f"Service '{SERVICE_NAME}' status = {svc_status}")

    # 4. Historical Data
    vn_stats = get_vnstat_usage(NETWORK_INTERFACE)
    print(f"Historical Data -> Daily: {vn_stats['daily']} GB | Weekly: {vn_stats['weekly']} GB | Monthly: {vn_stats['monthly']} GB")

    # 5. Bandwidth Speed (Download Only)
    dl_mbps = get_download_speed(NETWORK_INTERFACE)
    print(f"Current Speed: {dl_mbps} Mbps (Download)")

    print("-" * 60) # Separator

    # --- PHASE 2: SEND TO API ---

    # Send Users
    try:
        url = f"{API_BASE_URL}/total-users/{ipAddress}/{user_count}"
        resp = requests.post(url, timeout=10)
        print(f"[INFO] Users   → {resp.url} | Status: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Users API: {e}")

    # Send CPU
    try:
        url = f"{API_BASE_URL}/cpu-usage/{ipAddress}/{cpu_val}"
        resp = requests.post(url, timeout=10)
        print(f"[INFO] CPU     → {resp.url} | Status: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] CPU API: {e}")

    # Send Service Status
    try:
        url = f"{API_BASE_URL}/update-instance-status/{ipAddress}/openvpn/{PLATFORM}/{svc_status}"
        resp = requests.post(url, timeout=10)
        print(f"[INFO] Status  → {resp.url} | Status: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Status API: {e}")

    # Send Speed
    try:
        url = f"{API_BASE_URL}/server-speed/{ipAddress}/{dl_mbps}"
        resp = requests.post(url, timeout=10)
        print(f"[INFO] Speed   → {resp.url} | Status: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Bandwidth API: {e}")

    # Send History
    try:
        url = f"{API_BASE_URL}/historical-bandwidth/openvpn/{ipAddress}/{vn_stats['daily']}/{vn_stats['weekly']}/{vn_stats['monthly']}"
        resp = requests.post(url, timeout=10)
        print(f"[INFO] History → {resp.url} | Status: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] History API: {e}")

if __name__ == "__main__":
    send_data()
