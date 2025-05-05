from flask import Flask, send_file, jsonify, request
import socket
import time
import requests
import logging
import netifaces
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

discovered_devices = []

def get_default_interface_ip():
    try:
        gateways = netifaces.gateways()
        default_gateway = gateways.get('default', {}).get(netifaces.AF_INET)
        if not default_gateway:
            logger.warning("No default gateway found, falling back to 0.0.0.0")
            return '0.0.0.0'
        
        interface = default_gateway[1]
        addrs = netifaces.ifaddresses(interface).get(netifaces.AF_INET, [])
        if not addrs:
            logger.warning(f"No IPv4 address found for interface {interface}, falling back to 0.0.0.0")
            return '0.0.0.0'
        
        interface_ip = addrs[0]['addr']
        logger.info(f"Using interface {interface} with IP {interface_ip}")
        return interface_ip
    except Exception as e:
        logger.error(f"Error detecting default interface: {e}, falling back to 0.0.0.0")
        return '0.0.0.0'

@app.route('/')
def serve_html():
    return send_file('roku_control.html')

@app.route('/discover', methods=['POST'])
def discover_roku():
    global discovered_devices
    subnet = request.json.get('subnet', '10.0.3.0')
    logger.info(f"Starting discovery process for subnet {subnet}")
    devices = discover_ssdp()
    
    if not devices:
        logger.warning("SSDP found no devices, falling back to HTTP scanning")
        devices = discover_http(subnet)
    
    discovered_devices = devices
    logger.info(f"Discovery complete, found {len(devices)} devices: {[device['ip'] for device in devices]}")
    return jsonify(devices)

@app.route('/devices')
def get_devices():
    return jsonify(discovered_devices)

def discover_ssdp():
    MSEARCH = (
        'M-SEARCH * HTTP/1.1\r\n'
        'HOST: 239.255.255.250:1900\r\n'
        'MAN: "ssdp:discover"\r\n'
        'MX: 3\r\n'
        'ST: urn:roku-com:device:player:1-0\r\n'
        '\r\n'
    ).encode('utf-8')

    devices = []
    interface_ip = get_default_interface_ip()
    max_retries = 1

    for attempt in range(max_retries):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, 
                               socket.inet_aton('239.255.255.250') + socket.inet_aton(interface_ip))
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip))
            except socket.error as e:
                logger.error(f"Failed to configure multicast on attempt {attempt + 1}: {e}")
                continue
            
            sock.settimeout(6)
            sock.bind((interface_ip, 0))

            logger.debug(f"Sending SSDP M-SEARCH (attempt {attempt + 1}) on interface {interface_ip}")
            sock.sendto(MSEARCH, ('239.255.255.250', 1900))

            start_time = time.time()
            while time.time() - start_time < 6:
                try:
                    data, addr = sock.recvfrom(1024)
                    response = data.decode('utf-8', errors='ignore').lower()
                    logger.debug(f"Received SSDP response from {addr[0]}: {response[:100]}...")
                    
                    if 'roku' in response or 'tcl' in response:
                        ip = addr[0]
                        devices.append({'ip': ip, 'name': f'TCL Roku TV ({ip})'})
                except socket.timeout:
                    logger.debug("SSDP timeout reached")
                    break
                except Exception as e:
                    logger.error(f"Error processing SSDP response: {e}")
        except socket.error as e:
            logger.error(f"Socket error on attempt {attempt + 1}: {e}")
            if 'Address already in use' in str(e):
                logger.warning("Port conflict detected. Retrying with a different port.")
        finally:
            if sock:
                sock.close()
        if devices:
            break

    seen_ips = set()
    unique_devices = [d for d in devices if not (d['ip'] in seen_ips or seen_ips.add(d['ip']))]
    return unique_devices

def discover_http(subnet):
    logger.info(f"Starting HTTP scanning for subnet {subnet}")
    start_time = time.time()
    subnet_base = subnet.rsplit('.', 1)[0]
    devices = []

    def check_ip(i):
        ip = f'{subnet_base}.{i}'
        try:
            logger.debug(f"Checking {ip}")
            response = requests.get(f'http://{ip}:8060/query/device-info', timeout=0.5)
            if response.status_code == 200 and 'TCL' in response.text:
                logger.info(f"Found TCL Roku TV at {ip}")
                return {'ip': ip, 'name': f'TCL Roku TV ({ip})'}
        except requests.RequestException:
            pass
        return None

    with ThreadPoolExecutor(max_workers=40) as executor:
        results = executor.map(check_ip, range(1, 256))
        devices = [result for result in results if result is not None]

    scan_duration = time.time() - start_time
    logger.info(f"HTTP scan completed in {scan_duration:.2f} seconds")
    return devices

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

