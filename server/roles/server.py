import threading
import time

import psutil

from server.fault_detection import HandleAbnormalStateReport, HeartbeatMonitor
from server.fault_discovery import ServerCrashDiscovery
from server.election_manager import ElectionManager, STATE_LEADER, STATE_FOLLOWER
from utills.logger import get_logger

from .base import Role
from server.config import TYPE_LEADER, TYPE_FOLLOWER, HEARTBEAT_INTERVAL
from server.heartbeat import Heartbeat
from server.membership import MembershipManager

logger = get_logger("server_role")

class Server(Role):
    def __init__(self, server_id, network_manager, identity, leader_address=None):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager

        self.identity = identity

        # create membership manager according to identity
        self.membership_manager = MembershipManager(is_leader=(self.identity == TYPE_LEADER))
        self.leader_address = leader_address
        self.leader_id = None
        self.leader_latest_heartbeat = time.time()
        #服务器列表
        self.membership_list = {
            self.server_id: self.network_manager.ip_local
        }

        self.network_manager.set_callback(self.handle_messages)

        self._running = True
        #self.known_servers = set()

        # ---------------------------
        # Election manager (UDP-only)
        # ---------------------------
        initial_state = STATE_LEADER if self.identity == TYPE_LEADER else STATE_FOLLOWER
        self.election_manager = ElectionManager(
            self.server_id,
            self.network_manager,
            on_state_change=self.change_role,
            initial_state=initial_state,
        )
        self.election_manager.set_server_reference(self)
        if self.identity == TYPE_FOLLOWER and self.leader_address:
            # Leader ID will be set on REGISTER_ACK; seed IP now so follower waits calmly.
            self.election_manager.leader_ip = self.leader_address

    def start(self):
        # 启动网络监听
        self.network_manager.start_listening()
        self.election_manager.start()

        # leader role needs to initialize membership management immediately, while follower will initialize later
        if self.identity == TYPE_LEADER:
            print(f"[{self.identity}] Setting up {self.identity.lower()} role...")
            self.membership_manager.initialize_for_leader(True, {
                "server_id": self.server_id,
                "load_info": self.get_current_load(),
                "address": self.network_manager.ip_local
            })  
            # start listening for long-lived TCP connections from followers
            self.network_manager.start_leader_long_lived_listener()
            # start heartbeat manager
            self.heartbeat = Heartbeat(self, interval=HEARTBEAT_INTERVAL)
            self.heartbeat.start()
            # start fault detection monitor
            self.heartbeat_monitor = HeartbeatMonitor(self)
            self.heartbeat_monitor.start_timeout_checker()
            self.handle_abnormal_state_report = HandleAbnormalStateReport(self)
            self.fault_discovery = ServerCrashDiscovery(self)
        elif self.leader_address:
            self.register(self.leader_address)
        



        print(f"[Server] Initialized role: {self.identity}, Server ID: {self.server_id}")
        
            

    def register(self, leader_addr):
        print(f"[Follower] Registering with leader at {leader_addr}")
        self.network_manager.send_unicast(
            leader_addr,
            9001,
            "FOLLOWER_REGISTER",
            {"follower_id": self.server_id, 
             "load_info": self.get_current_load(),
             "follower_ip": self.network_manager.ip_local}
        )

         
    def handle_messages(self, msg_type, message, ip_sender):

        if msg_type == "STEAL_NOTIFICATION":
            stolen_server_id = message.get("stolen_server")
            stolen_group_id = message.get("stolen_group_id")
            new_group_id = message.get("new_group_id")
            new_group_member = message.get("new_group_member", {})
            logger.info(f"Received STEAL_NOTIFICATION: stolen_server={stolen_server_id}, stolen_group_id={stolen_group_id}, new_group_id={new_group_id}, new_group_member={new_group_member}")
            if self.server_id == stolen_server_id:
                logger.info(f"Server {self.server_id} is being stolen from group {stolen_group_id} to new group {new_group_id}")
                self.membership_manager.set_group_info(new_group_id, new_group_member)
            else:
                self.membership_manager.remove_group_member(stolen_server_id, stolen_group_id)

            logger.info(f"Updated group info: group_id={self.membership_manager.group_id}, group_members={self.membership_manager.group_members}")
        
        if self.identity == TYPE_LEADER:
            if msg_type == "WHO_IS_LEADER":
                print(f'[{self.identity}] receive message from new PC {ip_sender}: {msg_type} {message}')
                self.network_manager.send_broadcast(
                    "I_AM_LEADER", 
                    {"leader_id": self.server_id, "leader_ip": self.network_manager.ip_local}
                )
                #print(1)
            # handle follower registration
            elif msg_type == "FOLLOWER_REGISTER":
                follower_id = message.get("follower_id")
                follower_ip = message.get("follower_ip")
                load_info = message.get("load_info")
                # Ensure follower_id is integer
                follower_id = int(follower_id) if isinstance(follower_id, str) else follower_id
                print(f'[{self.identity}] Follower {follower_id} with IP: {follower_ip} registered.')
                self.membership_list[follower_id] = follower_ip
                print(f'[{self.identity}] Current membership list: {self.membership_list}')

                            
                self.membership_manager.add_server(follower_id, follower_ip, load_info)
                group_id, existed_members, steal_group_id, steal_server_id, steal_group_members = self.membership_manager.assign_group(follower_id)
               
                # Send membership excluding self (leader should not include itself for followers)
                membership_for_follower = {sid: sip for sid, sip in self.membership_list.items() if sid != self.server_id}
                
                self.network_manager.send_unicast(
                    follower_ip,
                    9001,
                    "REGISTER_ACK",
                    {"leader_id": self.server_id, 
                        "group_id": group_id,
                        "existed_members": existed_members,
                        "steal_group_id": steal_group_id,
                        "steal_server_id": steal_server_id,
                        "steal_group_members": steal_group_members,
                        "membership_list": membership_for_follower}
                )           
                # todo: notidy other followers about the new member

                for sid, sip in self.membership_list.items():
                    if sid != self.server_id:
                        self.network_manager.send_unicast(
                            sip,
                            9001,
                            "NEW_FOLLOWER_JOINED",
                            {"new_follower_id": follower_id, 
                             "new_follower_ip": follower_ip}
                        )
            
                #print('hhey')
            elif msg_type == "SERVER_FAILURE_REPORT":
                # fault_detetion handles this
                failed_ip = message.get("failed_ip")
                failed_port = message.get("failed_port")
                failed_server_id = message.get("failed_server_id")
                self.handle_abnormal_state_report.handle_report(failed_ip, failed_port, failed_server_id)
                logger.info(f"Received SERVER_FAILURE_REPORT: failed_ip={failed_ip}, failed_port={failed_port}")
        else:
            if msg_type == "REGISTER_ACK":
                #print('hhey')
                self.leader_id = message.get("leader_id")
                membership_raw = message.get("membership_list", {})
                self.membership_manager.set_group_info(message.get("group_id"), message.get("existed_members", {}))
                steal_group_id = message.get("steal_group_id")
                steal_server_id = message.get("steal_server_id")
                steal_group_members = message.get("steal_group_members", {})
                # if this follower is assigned to a group with steal_server
                # notify steal message
                if steal_group_id and steal_server_id:
                    for sid, sip in steal_group_members.items():
                        self.network_manager.send_unicast(
                            sip,
                            9001,
                            "STEAL_NOTIFICATION",
                            {"stolen_server": steal_server_id, 
                             "stolen_group_id": steal_group_id,
                             "new_group_id": message.get("group_id"),
                             "new_group_member": {self.server_id: self.network_manager.ip_local}
                            }
                        )
                    

                # start long-lived TCP connection to leader 
                self.network_manager.start_follower_long_lived_connector(self.leader_address,self.leader_id)

                # start heartbeat manager
                self.heartbeat = Heartbeat(self, interval=HEARTBEAT_INTERVAL)
                self.heartbeat.start()
                self.heartbeat_monitor = HeartbeatMonitor(self)
                self.heartbeat_monitor.start_timeout_checker()

                # Ensure all server_ids are integers
                self.membership_list = {}
                for sid, sip in membership_raw.items():
                    sid_int = int(sid) if isinstance(sid, str) else sid
                    self.membership_list[sid_int] = sip
                # Always include leader + self in membership view (needed for bully + role switching).
                if self.leader_id is not None and self.leader_address:
                    self.membership_list[int(self.leader_id)] = self.leader_address
                self.membership_list[self.server_id] = self.network_manager.ip_local
                print(f'[Follower] Registered with Leader {self.leader_id}. Current membership list: {self.membership_list}')

                # Seed ElectionManager with leader info + peers based on membership.
                try:
                    if self.election_manager:
                        self.election_manager.set_leader(self.leader_id, self.leader_address)
                        self.election_manager.update_peers_from_server()
                except Exception as e:
                    logger.debug(f"Failed to seed election manager after REGISTER_ACK: {e}")
            elif msg_type == "NEW_FOLLOWER_JOINED":
                new_follower_id = message.get("new_follower_id")
                new_follower_ip = message.get("new_follower_ip")
                if new_follower_id != self.server_id:
                    new_follower_id = int(new_follower_id) if isinstance(new_follower_id, str) else new_follower_id
                    self.membership_list[new_follower_id] = new_follower_ip
                    logger.info(f'[Follower] New follower joined: {new_follower_id} with IP: {new_follower_ip}. Updated membership list: {self.membership_list}')
                    try:
                        if self.election_manager:
                            self.election_manager.update_peers_from_server()
                    except Exception as e:
                        logger.debug(f"Failed to update election peers on NEW_FOLLOWER_JOINED: {e}")

            elif msg_type == "SERVER_REMOVED":
                removed_server_id = message.get("server_id")
                removed_group_id = message.get("group_id")
                removed_server_id = int(removed_server_id) if isinstance(removed_server_id, str) else removed_server_id
                self.membership_list.pop(removed_server_id, None)
                logger.info(f'[Follower] Server removed: {removed_server_id} from group {removed_group_id}. Updated membership list: {self.membership_list}')
                try:
                    if self.election_manager:
                        self.election_manager.update_peers_from_server()
                except Exception as e:
                    logger.debug(f"Failed to update election peers on SERVER_REMOVED: {e}")
            
            elif msg_type == "LEADER_CHANGED":
                new_leader_id = message.get("new_leader_id")
                new_leader_ip = message.get("new_leader_ip")
                print(f"[Server] Received LEADER_CHANGED notification: new leader is {new_leader_id} at {new_leader_ip}")
                
                if self.identity == TYPE_FOLLOWER:
                    self.leader_id = new_leader_id
                    self.leader_address = new_leader_ip
                    self.membership_list[new_leader_id] = new_leader_ip
                    
                    # 关闭旧连接，重新连接到新 Leader
                    try:
                        self.network_manager.unregister_connection(server_id=new_leader_id)
                        logger.debug(f"Closed old connection to {new_leader_id}")
                    except Exception as e:
                        logger.debug(f"Failed to unregister old connection: {e}")
                    
                    try:
                        self.network_manager.start_follower_long_lived_connector(new_leader_ip, new_leader_id)
                        logger.info(f"Reconnected to new leader {new_leader_id} at {new_leader_ip}")
                    except Exception as e:
                        logger.debug(f"Failed to reconnect to new leader: {e}")
    def change_role(self, new_role, leader_id):
        """Handle role change triggered by ElectionManager."""
        # Only log if role actually changes
        if self.identity == new_role:
            print(f"[Server] Role confirmed: {new_role} (Leader ID: {leader_id})")
            # Still update leader info even if role doesn't change
            if new_role == TYPE_FOLLOWER and leader_id != self.leader_id:
                self.leader_id = leader_id
                leader_ip = self.membership_list.get(leader_id)
                if leader_ip:
                    self.leader_address = leader_ip
            return
        
        print(f"[Server] Role change: {self.identity} -> {new_role} (Leader ID: {leader_id})")
        old_role = self.identity
        self.identity = new_role
        
        if new_role == TYPE_LEADER:
            print(f"[Server] Becoming LEADER (ID: {self.server_id})")
            self.leader_id = self.server_id
            self.leader_address = self.network_manager.ip_local
            
            # 关闭与旧 Leader 的连接（如果从 Follower 转变过来）
            if old_role == TYPE_FOLLOWER:
                try:
                    # 从消息中获取可能的旧 leader_id
                    old_leader_id = None
                    for sid in self.membership_list.keys():
                        if sid != self.server_id:
                            old_leader_id = sid
                            break
                    if old_leader_id:
                        self.network_manager.unregister_connection(server_id=old_leader_id)
                        logger.debug(f"Closed connection to old leader {old_leader_id}")
                except Exception as e:
                    logger.debug(f"Failed to unregister old leader connection: {e}")
            
            # Leader takes over membership management + long-lived listener + detection
            try:
                self.membership_manager.is_leader = True
                self.membership_manager.initialize_for_leader(True, {
                    "server_id": self.server_id,
                    "load_info": self.get_current_load(),
                    "address": self.network_manager.ip_local
                })
                
                # Initialize heartbeat timestamps for other known servers
                current_time = time.time()
                for server_id in self.membership_list.keys():
                    if server_id != self.server_id and server_id not in self.membership_manager.servers:
                        # Add other servers to membership with current timestamp
                        server_ip = self.membership_list.get(server_id)
                        if server_ip:
                            self.membership_manager.add_server(server_id, server_ip, {})
                            logger.info(f"[Leader] Initialized server {server_id} in membership")
                
            except Exception as e:
                logger.debug(f"Failed to initialize membership for new leader: {e}")

            # Start accepting long-lived follower connections (idempotent-ish for this project)
            try:
                self.network_manager.start_leader_long_lived_listener()
            except Exception as e:
                logger.debug(f"Failed to start leader long-lived listener: {e}")
            
            # 通知所有 Followers 重新连接到新 Leader
            self._notify_followers_new_leader()

            # Ensure heartbeat + fault detection are running in leader mode
            try:
                if not hasattr(self, "heartbeat") or self.heartbeat is None:
                    self.heartbeat = Heartbeat(self, interval=HEARTBEAT_INTERVAL)
                    self.heartbeat.start()
                # Send immediate heartbeat to stabilize new leadership
                self.heartbeat.send_heartbeat()
                logger.info(f"[Leader] Sent initial heartbeat after becoming leader")
            except Exception as e:
                logger.debug(f"Failed to start heartbeat after becoming leader: {e}")

            try:
                if not hasattr(self, "heartbeat_monitor") or self.heartbeat_monitor is None:
                    self.heartbeat_monitor = HeartbeatMonitor(self)
                    self.heartbeat_monitor.start_timeout_checker()
            except Exception as e:
                logger.debug(f"Failed to start heartbeat monitor after becoming leader: {e}")

            try:
                if not hasattr(self, "handle_abnormal_state_report") or self.handle_abnormal_state_report is None:
                    self.handle_abnormal_state_report = HandleAbnormalStateReport(self)
                if not hasattr(self, "fault_discovery") or self.fault_discovery is None:
                    self.fault_discovery = ServerCrashDiscovery(self)
            except Exception as e:
                logger.debug(f"Failed to start fault modules after becoming leader: {e}")
            
        elif new_role == TYPE_FOLLOWER:
            print(f"[Server] Becoming FOLLOWER (Leader ID: {leader_id})")
            self.leader_id = leader_id
            try:
                self.membership_manager.is_leader = False
            except Exception:
                pass
            # Find leader's IP from membership list
            leader_ip = self.membership_list.get(leader_id)
            if leader_ip:
                self.leader_address = leader_ip
                print(f"[Server] Leader address set to: {leader_ip}")
                # (Re)connect long-lived TCP to the leader so heartbeat can flow.
                try:
                    self.network_manager.start_follower_long_lived_connector(self.leader_address, self.leader_id)
                except Exception as e:
                    logger.debug(f"Failed to connect to leader after becoming follower: {e}")
            else:
                # Leader not in membership yet - will be set when we receive heartbeat
                print(f"[Server] Leader {leader_id} not in membership list yet")
    
    def _notify_followers_new_leader(self):
        """Notify all known Followers about new Leader and their need to re-register."""
        if self.identity != TYPE_LEADER:
            return
        
        logger.info(f"[Leader] Notifying followers about new leader: {self.server_id}")
        for server_id, server_ip in self.membership_list.items():
            if server_id != self.server_id:  # Skip self
                try:
                    self.network_manager.send_unicast(
                        server_ip,
                        9001,
                        "LEADER_CHANGED",
                        {
                            "new_leader_id": self.server_id,
                            "new_leader_ip": self.leader_address
                        }
                    )
                    logger.info(f"[Leader] Notified follower {server_id} at {server_ip} about new leader")
                except Exception as e:
                    logger.debug(f"Failed to notify follower {server_id} about leader change: {e}")
    
    def get_membership_list(self):
        """Return current membership list for ElectionManager."""
        return self.membership_list.copy()
    
    def update_membership_from_leader(self, membership_dict, leader_id):
        """Update membership list from leader's heartbeat (Follower only)."""
        # Convert all IDs to int
        self.membership_list = {}
        for sid, sip in membership_dict.items():
            sid_int = int(sid) if isinstance(sid, str) else sid
            self.membership_list[sid_int] = sip
        # Add leader (not included in broadcast)
        if leader_id not in self.membership_list:
            self.membership_list[leader_id] = self.leader_address
        # Add myself
        if self.server_id not in self.membership_list:
            self.membership_list[self.server_id] = self.network_manager.ip_local

    def run(self):
        pass

    def shutdown(self):
        pass

    def get_current_load(self):
        """获取当前负载信息"""
        pass
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent
        memory_available = psutil.virtual_memory().available
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent
        }
    

