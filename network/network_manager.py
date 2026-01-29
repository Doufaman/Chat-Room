'''
Implement the following functions:
    send and receive unicast(TCP)
    send and receive broadcast(UDP)
    send and receive multicast(UDP)
'''

import socket
import threading
import json
import struct

PORT_UNICAST = 9001
PORT_BROADCAST = 9000
PORT_MULTICAST = 9002

IP_BROADCAST = '255.255.255.255'
IP_MULTICAST = '224.0.0.1'

# TCP message header for length-prefix framing
HEADER_FORMAT = '!I'  
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

class NetworkManager:
    def __init__(self, 
                 ip_local, 
                 port_unicast=PORT_UNICAST, 
                 port_broadcast=PORT_BROADCAST, 
                 ip_multicast= IP_MULTICAST, 
                 port_multicast=PORT_MULTICAST):
        
        self.ip_local = ip_local
        self.port_unicast = port_unicast
        self.port_broadcast = port_broadcast
        self.ip_multicast = ip_multicast
        self.port_multicast = port_multicast

        # 消息回调映射（业务层通过这个获取数据）
        self.on_message_received = None 

    def set_callback(self, callback_func):
        """供 RoleManager 或 Leader 调用，设置消息回掉"""
        self.on_message_received = callback_func

    # message encode/decode functions
    def message_encode(self,  
                    message_type,
                    message):
        data = {"msg_type": message_type,
                "message": message,
                "sender_ip": self.ip_local
        }
        data_str = json.dumps(data, ensure_ascii=False)
        return data_str.encode()
    
    def message_decode(self, data):
        data_dic = json.loads(data.decode())
        message_type = data_dic.get("msg_type")
        message = data_dic.get("message")   
        sender_ip = data_dic.get("sender_ip")
        return message_type, message, sender_ip


    # send message functions
    def send_unicast(self, 
                     target_ip,
                     target_port, 
                     message_type,
                     message):
        """TCP unicast send with length-prefix framing"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.connect((target_ip, target_port))
                data = self.message_encode(message_type, message)
                # Add length prefix
                pkg_header = struct.pack(HEADER_FORMAT, len(data))
                pkg = pkg_header + data
                s.sendall(pkg)
        except Exception as e:
            print(f"[NetworkManager] Error sending unicast to {target_ip}:{target_port}: {e}")
            raise e

    def send_broadcast(self, 
                       message_type,
                       message):
        """UDP 广播发送"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            data = self.message_encode(message_type, message)
            s.sendto(data, ('<broadcast>', self.port_broadcast))

    #没调好
    def send_multicast(self, message_type,message):
        """UDP 组播发送"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            data = self.message_encode(message_type, message)
            s.sendto(data, (self.ip_multicast, self.port_multicast))
    

    # receive message functions
    def start_listening(self):
        threading.Thread(target=self.receive_unicast, daemon=True).start()
        threading.Thread(target=self.receive_broadcast, daemon=True).start()
        #threading.Thread(target=self.receive_multicast, daemon=True).start()

    def receive_unicast(self):
        """TCP server receive with length-prefix framing"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            server.bind(('0.0.0.0', self.port_unicast)) # 绑定所有网卡
            server.listen(5)
            while True:
                conn, addr = server.accept()
                threading.Thread(target=self._handle_tcp_connection, args=(conn, addr), daemon=True).start()

    def _handle_tcp_connection(self, conn, addr):
        """Handle a TCP connection in a separate thread"""
        try:
            with conn:
                while True:
                    # Read header (4 bytes for message length)
                    header = self._read_exact(conn, HEADER_SIZE)
                    if not header:
                        break
                    
                    body_len = struct.unpack(HEADER_FORMAT, header)[0]
                    
                    # Read body
                    body = self._read_exact(conn, body_len)
                    if not body:
                        break
                    
                    if self.on_message_received:
                        msg_type, content, sender_ip = self.message_decode(body)
                        self.on_message_received(msg_type, content, sender_ip)
        except Exception as e:
            print(f"[NetworkManager] TCP connection error from {addr}: {e}")

    def _read_exact(self, sock, n):
        """Helper to read exactly n bytes from socket"""
        data = bytearray()
        while len(data) < n:
            try:
                packet = sock.recv(n - len(data))
                if not packet:
                    return None
                data.extend(packet)
            except OSError:
                return None
        return bytes(data)

    def receive_broadcast(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # For macOS/BSD: SO_REUSEPORT is required to bind multiple processes to same port
            if hasattr(socket, 'SO_REUSEPORT'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(('', self.port_broadcast))
            while True:
                data, addr = sock.recvfrom(1024)
                if addr[0] == self.ip_local: # 忽略自己发出的广播
                    continue
                if data and self.on_message_received:
                    msg_type, message, sender_ip = self.message_decode(data)
                    # 触发回调
                    self.on_message_received(msg_type, message, sender_ip)

    #先不管multicast
    def receive_multicast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind((self.host_ip, self.mcast_port))
        mreq = socket.inet_aton(self.mcast_group) + socket.inet_aton(self.host_ip)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        while True:
            data, addr = sock.recvfrom(1024)
            if self.on_message_received:
                self.on_message_received('MULTICAST', addr, data.decode())
    