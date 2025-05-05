from flask import Flask, request, jsonify, send_from_directory
import netifaces
import socket
import time
import threading
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# Store discovered devices
devices = []

def get_default_interface():
    gateways = netifaces.gateways()
    default_gateway = gateways.get('default')
    if default_gateway and netifaces.AF_INET in default_gateway:
        interface = default_gateway[netifaces.AF_INET][1]
        return interface
    return None

def get_interface_ip(interface):
    try:
        addrs = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addrs:
            for addr in addrs[netifaces.AF_INET]:
                return addr['addr']
    except Exception as e:
        print(f"Error getting IP for interface {interface}: {e}")
    return None

def ssdp_discover(timeout=5):
    global devices
    MSEARCH = (
        'M-SEARCH * HTTP/1.1\r\n'
        'HOST: 239.255.255.250:1900\r\n'
        'MAN: "ssdp:discover"\r\n'
        'MX: 3\r\n'
        'ST: roku:ecp\r\n'
        '\r\n'
    ).encode('utf-8')
    MULTICAST_ADDRESS = '239.255.255.250'
    PORT = 1900

    interface = get_default_interface()
    if not interface:
        return []

    local_ip = get_interface_ip(interface)
    if not local_ip:
        return []

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)

    try:
        sock.bind((local_ip, 0))
        sock.sendto(MSEARCH, (MULTICAST_ADDRESS, PORT))
        start_time = time.time()
        temp_devices = []
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(1024)
                response = data.decode('utf-8')
                if 'roku:ecp' in response:
                    for line in response.split('\n'):
                        if line.startswith('LOCATION:'):
                            location = line.split(':', 1)[1].strip()
                            try:
                                device_info = requests.get(location, timeout=3).text
                                root = ET.fromstring(device_info)
                                friendly_name = root.find('.//{urn:schemas-upnp-org:device-1-0}friendlyName').text
                                temp_devices.append({
                                    'ip': addr[0],
                                    'name': f"TCL Roku TV ({addr[0]})"
                                })
                            except Exception as e:
                                print(f"Error parsing device at {location}: {e}")
            except socket.timeout:
                break
            except Exception as e:
                print(f"SSDP error: {e}")
        devices = temp_devices
        return devices
    finally:
        sock.close()

def http_scan(subnet):
    global devices
    base_ip = subnet.rsplit('.', 1)[0]
    temp_devices = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = []
        for i in range(1, 256):
            ip = f"{base_ip}.{i}"
            futures.append(executor.submit(check_device, ip))
        for future in futures:
            result = future.result()
            if result:
                temp_devices.append(result)
    devices = temp_devices
    return devices

def check_device(ip):
    try:
        response = requests.get(f"http://{ip}:8060/query/device-info", timeout=2)
        if response.status_code == 200:
            root = ET.fromstring(response.text)
            friendly_name = root.find('user-device-name').text or root.find('default-device-name').text
            return {'ip': ip, 'name': f"TCL Roku TV ({ip})"}
    except Exception:
        pass
    return None

@app.route('/')
def index():
    return send_from_directory('.', 'roku_control.html')

@app.route('/discover', methods=['POST'])
def discover():
    global devices
    data = request.get_json()
    subnet = data.get('subnet')
    if not subnet:
        return jsonify({'error': 'Subnet is required'}), 400
    try:
        devices = ssdp_discover()
        if not devices:
            devices = http_scan(subnet)
        return jsonify(devices)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/devices')
def get_devices():
    return jsonify(devices)

@app.route('/keypress', methods=['POST'])
def keypress():
    data = request.get_json()
    ip = data.get('ip')
    key = data.get('key')
    if not ip or not key:
        return jsonify({'error': 'IP and key are required'}), 400
    try:
        response = requests.post(f"http://{ip}:8060/keypress/{key}", timeout=5)
        if response.status_code == 200:
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': f"Failed to send keypress: status {response.status_code}"}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('.', 'manifest.json')

@app.route('/service-worker.js')
def serve_sw():
    return send_from_directory('.', 'service-worker.js')

@app.route('/icons/<path:filename>')
def serve_icons(filename):
    return send_from_directory('icons', filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
    