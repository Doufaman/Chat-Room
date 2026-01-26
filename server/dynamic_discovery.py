
import time

import socket


#from roles.backup import Backup 



'''
class RoleManager:
    # critical resources
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
            
            # 启动网络监听
            self.network_manager.start_listening()

            print(f"[Server] Initialized role: {role_name}")'''


def dynamic_discovery(ip_local, timeout = 3.0):
    print(f"[Server] Discovery phase started. Waiting {timeout}s for Leader response...")

    # try to find leader
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1) #允许广播
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #允许端口复用
    sock.bind(('', 9000))  # 绑定到指定的本地IP
    sock.settimeout(timeout)
    try:
        # NetworkManager也能用
        #nw = NetworkManager(ip_local='192.168.1.102')
        #nw.send_broadcast("WHO_IS_LEADER", "hey")
        
        # TOOD : modify message format
        broad_msg = {"msg_type": "WHO_IS_LEADER",
                     "message": "hey",
                     "sender_ip": ip_local}
        sock.sendto(broad_msg.encode(), ('255.255.255.255', 9000))
        time.sleep(0.5) #确保广播发出去
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                received_msg = data.decode()
                # TODO2: modify message format
                msg_type = received_msg.get("msg_type")
                message = received_msg.get("message")
                sender_ip = received_msg.get("sender_ip")
                if sender_ip == ip_local: # 忽略自己发出的广播
                    continue
                
                if msg_type == "I_AM_LEADER":
                    print(f"[Server] Leader found at {sender_ip}: {msg_type} {message}")
                    # modify2: move initialization out of dynamic_discovery 
                    # current_server = RoleManager(ip_local=ip_local)
                    # current_server.initialize_role("follower")
                    return "follower", sender_ip
                elif msg_type == "WHO_IS_LEADER":
                    # ignore other WHO_IS_LEADER messages
                    continue

            except socket.timeout:
                print("No response from Leader within timeout.")
                # modify2: move initialization out of dynamic_discovery
                # initiallize as leader
                # current_server = RoleManager(ip_local=ip_local)
                # current_server.initialize_role("leader")
                return "leader", None
    finally:
        sock.close()








