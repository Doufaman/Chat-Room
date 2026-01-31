import socket
import sys
import os
import time
import json
import struct

# 路径设置，确保能导入 modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir) # 假设此脚本在 group communication 根目录下
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 简单的发送辅助函数（复制自 network/messenger.py 的逻辑，简化版）
def send_raw_msg(sock, msg_dict):
    msg_json = json.dumps(msg_dict)
    msg_bytes = msg_json.encode('utf-8')
    header = struct.pack('!I', len(msg_bytes))
    sock.sendall(header + msg_bytes)

def run_test():
    server_ip = '127.0.0.1'
    server_port = 6000
    
    tester_id = "ChaosTester"
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server_ip, server_port))
        print(f"[*] Connected to Server as {tester_id}")

        # -------------------------------------------------
        # Step 1: 发送 JOIN
        # -------------------------------------------------
        print("[1] Sending JOIN...")
        join_msg = {
            'type': 'JOIN',
            'sender': tester_id,
            'vector_clock': {tester_id: 0},
            'content': f'{tester_id} joined for testing.'
        }
        send_raw_msg(sock, join_msg)
        time.sleep(1) # 等待对方处理 JOIN

        # -------------------------------------------------
        # Step 2: 故意先发送 Message 2 (Clock = 2)
        # 这就是“未来的消息”，此时接收方只知道 {Tester: 0}
        # -------------------------------------------------
        print("[2] Sending Message 2 (The Future Message)...")
        msg_2 = {
            'type': 'CHAT',
            'sender': tester_id,
            'vector_clock': {tester_id: 2}, # 注意：这里跳过了 1
            'content': 'MSG_2: I am from the future (Clock 2). I should be BUFFERED.'
        }
        send_raw_msg(sock, msg_2)
        
        print("    -> Message 2 sent. Watch the client console. It should NOT appear yet.")
        time.sleep(5) # 暂停5秒，让你有时间观察 Client 端确实没有打印这条消息

        # -------------------------------------------------
        # Step 3: 补发 Message 1 (Clock = 1)
        # 这就是“缺失的消息”
        # -------------------------------------------------
        print("[3] Sending Message 1 (The Missing Message)...")
        msg_1 = {
            'type': 'CHAT',
            'sender': tester_id,
            'vector_clock': {tester_id: 1}, # 补上 1
            'content': 'MSG_1: I was delayed (Clock 1). I should appear NOW, followed immediately by MSG_2.'
        }
        send_raw_msg(sock, msg_1)
        print("    -> Message 1 sent.")

        print("[*] Test finished. Closing connection.")
        time.sleep(1)
        sock.close()

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_test()