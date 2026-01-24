'''
Implement the following functions:
    send and receive unicast(TCP)
    send and receive broadcast(UDP)
    send and receive multicast(UDP)
'''

import socket
import threading

PORT_UNICAST = 9001
PORT_BROADCAST = 9000
PORT_MULTICAST = 9002

IP_BROADCAST = '255.255.255.255'
IP_MULTICAST = '224.0.0.1'

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


    # message encode/decode functions
    def message_encode(self,  
                    message_type,
                    message):
        data = f"{message_type}|{message}|{self.ip_local}"
        return data.encode()
    
    def message_decode(self, data):
        data = data.decode()
        message_type, message, sender_ip = data.split("|") # message里面有|就寄了
        return message_type, message, sender_ip


    # send message functions
    def send_unicast(self, target_ip, message_type,message):
        # TCP unicast send
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((target_ip, self.port_unicast))
            data = self.message_encode(message_type, message)
            s.sendall(data)

    def send_broadcast(self, message_type,message):
        """UDP 广播发送"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            data = self.message_encode(message_type, message)
            s.sendto(data, ('<broadcast>', self.port_broadcast))

    def send_multicast(self, message_type,message):
        """UDP 组播发送"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            data = self.message_encode(message_type, message)
            s.sendto(data, (self.ip_multicast, self.port_multicast))
    

    '''以下代码不知道能不能跑'''
    # receive message functions
    def start_listening(self):
        threading.Thread(target=self.receive_unicast, daemon=True).start()
        threading.Thread(target=self.receive_broadcast, daemon=True).start()
        #threading.Thread(target=self.receive_multicast, daemon=True).start()

    def receive_unicast(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((self.host_ip, self.unicast_port))
        server.listen(5)
        while True:
            conn, addr = server.accept()
            data = conn.recv(1024)
            if self.on_message_received:
                self.on_message_received('UNICAST', addr, data.decode())
            conn.close()

    def receive_broadcast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.host_ip, self.bcast_port))
        while True:
            data, addr = sock.recvfrom(1024)
            if self.on_message_received:
                self.on_message_received('BROADCAST', addr, data.decode())
    

    #先不管multicast
    def receive_multicast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host_ip, self.mcast_port))
        mreq = socket.inet_aton(self.mcast_group) + socket.inet_aton(self.host_ip)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        while True:
            data, addr = sock.recvfrom(1024)
            if self.on_message_received:
                self.on_message_received('MULTICAST', addr, data.decode())
    