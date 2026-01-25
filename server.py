import threading
import time
from typing import Dict, Type, Optional
import socket

from roles.leader import Leader
from roles.follower import Follower
#from roles.backup import Backup 

from network.network_manager import NetworkManager


class RoleManager:
    registry: Dict[str, Type] = {
        "leader": Leader,
        "follower": Follower,
        #"backup": Backup,
    }

    #initialization
    def __init__(self, ip_local:str):
        self._lock = threading.RLock()
        self._ip_local = ip_local

        # 统一的网络管理
        self.network_manager = NetworkManager(ip_local=self._ip_local)

        # 状态维护
        self._current_role_name: Optional[str] = None
        self._role_instance = None

    def initialize_role(self, role_name: str):
        role_name = role_name.lower()
        with self._lock:
            if role_name not in self.registry:
                raise ValueError(f"Unknown role: {role_name}")
            if self._role_instance:
                print("There is already a role instance.")
            role_class = self.registry[role_name]
            self._role_instance = role_class(self.network_manager)
            self._current_role_name = role_name

            print(f"[RoleManager] Initialized role: {role_name}")


def dynamic_discovery(ip_local, timeout = 3.0):
    print(f"Discovery phase started. Waiting {timeout}s for Leader response...")

    # try to find leader
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        # NetworkManager也能用
        #nw = NetworkManager(ip_local='192.168.1.102')
        #nw.send_broadcast("WHO_IS_LEADER", "hey")
        
        broad_msg = f"WHO_IS_LEADER|hey|{ip_local}"
        sock.sendto(broad_msg.encode(), ('255.255.255.255', 9000))

        data = sock.recvfrom(1024)
        received_msg = data.decode()
        print(received_msg)
        current_server = RoleManager(ip_local=ip_local)
        current_server.initialize_role("follower")
        return current_server

    except socket.timeout:
        print("No response from Leader within timeout.")
        # initiallize as leader
        current_server = RoleManager(ip_local=ip_local)
        current_server.initialize_role("leader")
        return current_server
    finally:
        sock.close()


if __name__ == '__main__':
    MY_IP = input("请输入服务器 IP 地址: ")
    print(f"Starting server with IP: {MY_IP}")

    current_server = dynamic_discovery(MY_IP) #使用当前IP进行动态发现
    





