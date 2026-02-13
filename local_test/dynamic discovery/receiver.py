import threading
import socket

def discovery_thread():
    # 专门负责 6000 端口的广播发现
    ds_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ds_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ds_sock.bind(('0.0.0.0', 6000))
    while True:
        data, addr = ds_sock.recvfrom(1024)
        print(f"在6000端口收到广播:{data}")
        # 回复对方：我的正式服务在 300 端口
        ds_sock.sendto(b"MY_SERVICE_PORT:300", addr)

def chat_thread():
    # 专门负责 300 端口的聊天业务
    chat_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    chat_sock.bind(('0.0.0.0', 300))
    while True:
        data, addr = chat_sock.recvfrom(1024)
        print(f"在300端口收到聊天消息:{data}")

# 启动两个“分身”
threading.Thread(target=discovery_thread, daemon=True).start()
chat_thread()



