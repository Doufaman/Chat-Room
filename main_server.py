import time
import uuid

from utills.logger import setup_logger
import logging

from network.network_manager import NetworkManager

from server.roles.server import Server
# from server.roles.leader import Leader
# from server.roles.follower import Follower
from server.dynamic_discovery import dynamic_discovery
from server.election_manager import ElectionManager

DEBUG = True  # or False

if DEBUG:
    setup_logger(logging.DEBUG)
else:
    setup_logger(logging.INFO)

class StartupEngine:
    def __init__(self,
                 self_ip,
                 #config
                 ):
        # create unique server ID
        self.self_ip = self_ip
        
        #self.server_id = str(uuid.uuid4())
        self.server_id = uuid.uuid4().int % (10**9)  # using 9-digit number to identify server

        # --- Core modules ---
        # self.comm = Communication(config)
        # self.discovery = Discovery(self.comm)
        # self.membership = MembershipManager()
        # self.heartbeat = HeartbeatManager(self)
        # self.election = ElectionManager(self)
        # self.recovery = RecoveryManager(self)
        # self.chat = ChatroomManager(self)
    
    def start(self, self_ip):
        # 1. 启动通信
        # self.comm.start()
        
        # 2. 进入 discovery
        current_identity, leader_address = dynamic_discovery(ip_local = self_ip) #使用当前IP进行动态发现

        # 生成对应的network manager
        #network_manager, leader_address = NetworkManager(ip_local=self_ip)
        network_manager = NetworkManager(ip_local=self_ip)

        Server(self.server_id, network_manager, identity=current_identity, leader_address=leader_address).start()

        # Start the Election Manager 
        election_manager = ElectionManager(self.server_id, network_manager)
        election_manager.start()
        # if current_identity == "follower":
        #     Follower(self.server_id, network_manager, leader_address).start()
        # else:
        #     Leader(self.server_id, network_manager).start()

    
    # --------------------
    # State transitions
    # --------------------
    
    def become_follower(self, leader_addr):
        self.state = "FOLLOWER"
        self.leader_addr = leader_addr
        
        # 向 leader 注册: 要携带目前的load_info和address信息(?)
        self.comm.send(leader_addr, {
            "type": "JOIN_SERVER",
            "server_id": self.server_id
        })
        
        # 启动 follower 心跳
        self.heartbeat.start_follower_heartbeat()
    
    def become_leader(self):
        self.state = "LEADER"
        self.leader_addr = self.get_own_address()
        
        # 初始化 membership
        self.membership.add_server(self.server_id, self.leader_addr)
        
        # 启动 leader 心跳与 timeout 检测
        self.heartbeat.start_leader_heartbeat()
        self.heartbeat.start_timeout_checker()
    
    def become_candidate(self):
        self.state = "CANDIDATE"
        
        # 停止普通 heartbeat
        self.heartbeat.stop()
        
        # 发起选举
        self.election.start_election()
    
    # --------------------
    # Helper methods
    # --------------------
    
    def get_own_address(self):
        """获取本服务器的地址"""
        # 需要根据实际网络配置实现
        # 这里返回一个占位符
        return f"server_{self.server_id}_addr"
    
    # --------------------
    # Event handlers
    # --------------------
    
    def handle_events(self):
        msg = self.comm.receive()
        
        if msg["type"] == "HEARTBEAT": 
            self.heartbeat.handle_heartbeat(msg)
        
        elif msg["type"] == "HEARTBEAT_TIMEOUT":
            if self.state == "FOLLOWER":
                self.become_candidate()
        
        elif msg["type"] == "ELECTION":
            self.election.handle_election(msg)
        
        elif msg["type"] == "COORDINATOR":
            self.become_follower(msg["leader_addr"])
        
        elif msg["type"] == "JOIN_SERVER" and self.state == "LEADER":
            """
            1. membership.add_server
            2. membership.asiign_group
            3. inform related data to this server
            """
            self.membership.add_server(
                msg["server_id"], msg["addr"]
            )
        
        elif msg["type"] == "CLIENT_JOIN":
            self.chat.handle_client_join(msg)
        
        elif msg["type"] == "SERVER_CRASH" and self.state == "LEADER":
            self.recovery.handle_server_crash(msg["server_id"])

# modify1: move startup code into main.py
if __name__ == '__main__':
    MY_IP = input("请输入服务器 IP 地址: ")
    print(f"[Server] Starting server with IP: {MY_IP}")

    startup_engine = StartupEngine(MY_IP)
    startup_engine.start(MY_IP)

    # 保持主线程运行，让后台监听线程继续工作
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Server] Shutting down...")
        # modify: move the start od dynamic_discovery into startupengine
        # if current_server._role_instance:
        #    current_server._role_instance.shutdown()