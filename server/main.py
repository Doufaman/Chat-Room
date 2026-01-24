from utills.logger import setup_logger
import logging

DEBUG = True  # or False

if DEBUG:
    setup_logger(logging.DEBUG)
else:
    setup_logger(logging.INFO)

class Server:
    def __init__(self, server_id, config):
        self.server_id = server_id
        self.state = "INIT"     # INIT / FOLLOWER / LEADER / CANDIDATE
        
        # --- Core modules ---
        # self.comm = Communication(config)
        # self.discovery = Discovery(self.comm)
        # self.membership = MembershipManager()
        # self.heartbeat = HeartbeatManager(self)
        # self.election = ElectionManager(self)
        # self.recovery = RecoveryManager(self)
        # self.chat = ChatroomManager(self)
        
        self.leader_addr = None
    
    def start(self):
        # 1. 启动通信
        self.comm.start()
        
        # 2. 进入 discovery
        self.state = "DISCOVERY"
        leader_addr = self.discovery.discover_leader()
        
        if leader_addr:
            self.become_follower(leader_addr)
        else:
            self.become_leader()
        
        # 3. 主循环（事件驱动）
        while True:
            self.handle_events()
    
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