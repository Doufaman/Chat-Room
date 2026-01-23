import threading
import time
from typing import Dict, Type
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
    def __init__(self, ip:str):
        self._lock = threading.RLock()
        self._my_ip = ip

        # 统一的网络管理
        self.network = NetworkManager(host_ip=self._my_ip)
        #self.network.start_listening()

        # 状态维护
        self._current_role_name = None
        self._role_instance = None
        self._thread = None
        self._leader_found = threading.Event() #find leader or not

    def _initialize_role(self, role_name: str):
        with self._lock:
            role_class = self.registry[role_name]
            self._role_instance = role_class(self.network)
            self._current_role_name = role_name


def dynamic_discovery(timeout = 3.0):
    print(f"Discovery phase started. Waiting {timeout}s for Leader response...")

    # try to find leader
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        broad_msg = "WHO_IS_LEADER"
        sock.sendto(broad_msg.encode(), ('255.255.255.255', 9000))

        data = sock.recvfrom(1024)
        received_msg = data.decode()
        print(received_msg)

    except socket.timeout:
        print("No response from Leader within timeout.")
    finally:
        sock.close()


if __name__ == '__main__':
    MY_IP = input("请输入服务器 IP 地址: ")
    print(f"Starting server with IP: {MY_IP}")

    dynamic_discovery()
    





