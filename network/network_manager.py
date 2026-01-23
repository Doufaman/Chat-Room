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

class NetworkManager:
    def __init__(self, host_ip, unicast_port=PORT_UNICAST, bcast_port=PORT_BROADCAST, mcast_group="224.0.0.1", mcast_port=PORT_MULTICAST):
        self.host_ip = host_ip
        self.unicast_port = unicast_port
        self.bcast_port = bcast_port
        self.mcast_group = mcast_group
        self.mcast_port = mcast_port
        
        # 消息回调映射（业务层通过这个获取数据）
        self.on_message_received = None 

    # send message functions
    '''
    def send_unicast(self, target_ip, data):
        # TCP unicast send
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((target_ip, self.tcp_port))
            s.sendall(data.encode())
            '''

    def send_broadcast(self, data):
        """UDP 广播发送"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(data.encode(), ('<broadcast>', self.bcast_port))

    '''
    def send_multicast(self, data):
        """UDP 组播发送"""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            s.sendto(data.encode(), (self.mcast_group, self.mcast_port))
    '''

    '''
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
    '''

    #先不管multicast
    '''
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
    '''