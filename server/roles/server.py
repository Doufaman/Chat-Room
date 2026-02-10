import threading
import time

import psutil

from server.fault_detection import HandleAbnormalStateReport, HeartbeatMonitor
from server.fault_discovery import ServerCrashDiscovery
from server.election_manager import ElectionManager, STATE_LEADER, STATE_FOLLOWER
from server.chatroom_manager import ChatroomManager
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
        # Server list
        self.membership_list = {
            self.server_id: self.network_manager.ip_local
        }
        
        # Chatroom list (all servers maintain same replica, similar to membership_list)
        self.chatroom_list = {}  # {chatroom_id: {name, server_id, server_ip, port, clients_count}}
        self.chatroom_lock = threading.Lock()
        
        # Initialize ChatroomManager (each server has one for managing local chatroom instances)
        self.chatroom_manager = ChatroomManager(
            server_id=self.server_id,
            local_ip=self.network_manager.ip_local,
            membership_manager=self.membership_manager,
            on_client_count_change=self._on_chatroom_client_count_change
        )

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

    def _on_chatroom_client_count_change(self, room_id, new_count):
        """
        Callback when a chatroom's client count changes.
        Update chatroom_list and broadcast to all servers.
        """
        chatroom_id = f"{self.server_id}_{room_id}"
        logger.info(f"[Server {self.server_id}] Chatroom {chatroom_id} client count changed to {new_count}")
        
        # Update local chatroom_list
        with self.chatroom_lock:
            if chatroom_id in self.chatroom_list:
                self.chatroom_list[chatroom_id]['clients_count'] = new_count
        
        # Broadcast UPDATE_CHATROOM to all servers
        for server_id, server_ip in self.membership_list.items():
            if server_id != self.server_id:
                self.network_manager.send_unicast(
                    server_ip,
                    9001,
                    "UPDATE_CHATROOM",
                    {
                        "chatroom_id": chatroom_id,
                        "updates": {"clients_count": new_count}
                    }
                )

    def start(self):
        # Start network listening
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
        
        # All servers handle these messages
        if msg_type == "NEW_CHATROOM":
            # Leader broadcasts new chatroom notification
            chatroom_info = message.get("chatroom_info")
            if chatroom_info:
                with self.chatroom_lock:
                    chatroom_id = chatroom_info["chatroom_id"]
                    self.chatroom_list[chatroom_id] = chatroom_info
                    logger.info(f"[Server {self.server_id}] Added chatroom {chatroom_id} to list: {chatroom_info}")
        
        elif msg_type == "CHATROOM_DELETED":
            # Leader broadcasts chatroom deletion notification
            logger.info(f"[Server {self.server_id}] Received CHATROOM_DELETED for chatroom_ids: {message.get('chatroom_ids', [])}")
            chatroom_ids = message.get("chatroom_ids", [])
            if chatroom_ids:
                for chatroom_id in chatroom_ids:
                    with self.chatroom_lock:
                        if chatroom_id in self.chatroom_list:
                            del self.chatroom_list[chatroom_id]
                            logger.info(f"[Server {self.server_id}] Removed chatroom {chatroom_id} from list")
                            logger.info(f"[Server {self.server_id}] Current chatroom_list after deletion: {self.chatroom_list}")
    
        elif msg_type == "UPDATE_CHATROOM":
            # Update chatroom info (e.g., client count change)
            chatroom_id = message.get("chatroom_id")
            updates = message.get("updates", {})
            if chatroom_id and updates:
                with self.chatroom_lock:
                    if chatroom_id in self.chatroom_list:
                        self.chatroom_list[chatroom_id].update(updates)
                        logger.info(f"[Server {self.server_id}] Updated chatroom {chatroom_id}: {updates}")
        
        if self.identity == TYPE_LEADER:
            if msg_type == "WHO_IS_LEADER":
                print(f'[{self.identity}] receive message from new PC {ip_sender}: {msg_type} {message}')
                self.network_manager.send_broadcast(
                    "I_AM_LEADER", 
                    {"leader_id": self.server_id, "leader_ip": self.network_manager.ip_local}
                )
            
            elif msg_type == "GET_CHATROOM_LIST":
                # Client requests chatroom list
                logger.info(f'[Leader] Client {ip_sender} requesting chatroom list')
                with self.chatroom_lock:
                    # Filter out chatrooms from servers that are no longer in membership_list
                    active_chatrooms = [
                        room for room in self.chatroom_list.values()
                        if room.get('server_id') in self.membership_list
                    ]
                self.network_manager.send_broadcast(
                    "CHATROOM_LIST",
                    {"chatrooms": active_chatrooms}
                )
                logger.info(f'[Leader] Sent {len(active_chatrooms)} chatrooms to client {ip_sender}')
            
            elif msg_type == "CREATE_CHATROOM":
                # Client requests to create chatroom
                chatroom_name = message.get("name", "Unnamed Room")
                target_server_id = message.get("server_id")  # Optional: specify which server to create on
                
                # If no server specified, select the server with lowest load
                if target_server_id is None:
                    target_server_id = self._select_server_for_chatroom()
                
                logger.info(f'[Leader] Creating chatroom "{chatroom_name}" on server {target_server_id}')
                
                # If target is the Leader itself, create directly
                if target_server_id == self.server_id:
                    room_info = self.chatroom_manager.create_room(chatroom_name)
                    if room_info:
                        chatroom_id = f"{self.server_id}_{room_info['room_id']}"
                        chatroom_info = {
                            "chatroom_id": chatroom_id,
                            "name": chatroom_name,
                            "server_id": self.server_id,
                            "server_ip": self.network_manager.ip_local,
                            "port": room_info['port'],
                            "clients_count": 0
                        }
                        
                        # Update local list
                        with self.chatroom_lock:
                            self.chatroom_list[chatroom_id] = chatroom_info
                        
                        # Broadcast to all servers
                        for server_id, server_ip in self.membership_list.items():
                            if server_id != self.server_id:
                                self.network_manager.send_unicast(
                                    server_ip,
                                    9001,
                                    "NEW_CHATROOM",
                                    {"chatroom_info": chatroom_info}
                                )
                        
                        # Notify the requesting client (UDP broadcast)
                        self.network_manager.send_broadcast(
                            "CHATROOM_CREATED",
                            {"chatroom_info": chatroom_info}
                        )
                        
                        logger.info(f'[Leader] Created and broadcasted chatroom: {chatroom_id}')
                else:
                    # Notify target server to create actual chatroom instance
                    target_ip = self.membership_list.get(target_server_id)
                    if target_ip:
                        self.network_manager.send_unicast(
                            target_ip,
                            9001,
                            "CREATE_CHATROOM_LOCAL",
                            {"name": chatroom_name, "requester_ip": ip_sender}
                        )
            
            elif msg_type == "CHATROOM_CREATED":
                # Server reports back after creating chatroom
                chatroom_info = message.get("chatroom_info")
                requester_ip = message.get("requester_ip")
                
                if chatroom_info:
                    # Update local list
                    with self.chatroom_lock:
                        chatroom_id = chatroom_info["chatroom_id"]
                        self.chatroom_list[chatroom_id] = chatroom_info
                    
                    # Broadcast to all servers
                    for server_id, server_ip in self.membership_list.items():
                        if server_id != self.server_id:
                            self.network_manager.send_unicast(
                                server_ip,
                                9001,
                                "NEW_CHATROOM",
                                {"chatroom_info": chatroom_info}
                            )
                    
                    # Notify the requesting client (UDP broadcast)
                    self.network_manager.send_broadcast(
                        "CHATROOM_CREATED",
                        {"chatroom_info": chatroom_info}
                    )
                    
                    logger.info(f'[Leader] Broadcasted new chatroom: {chatroom_id}')
            
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
            # Follower handles messages
            if msg_type == "CREATE_CHATROOM_LOCAL":
                # Leader instructs this server to create chatroom instance
                chatroom_name = message.get("name", "Unnamed Room")
                requester_ip = message.get("requester_ip")
                
                logger.info(f'[Follower {self.server_id}] Creating local chatroom: {chatroom_name}')
                
                # Use ChatroomManager to create actual chatroom
                room_info = self.chatroom_manager.create_room(chatroom_name)
                
                if room_info:
                    # Construct chatroom info
                    chatroom_id = f"{self.server_id}_{room_info['room_id']}"
                    chatroom_info = {
                        "chatroom_id": chatroom_id,
                        "name": chatroom_name,
                        "server_id": self.server_id,
                        "server_ip": self.network_manager.ip_local,
                        "port": room_info['port'],
                        "clients_count": 0
                    }
                    
                    # Report to Leader
                    leader_ip = self.membership_list.get(self.leader_id)
                    if leader_ip:
                        self.network_manager.send_unicast(
                            leader_ip,
                            9001,
                            "CHATROOM_CREATED",
                            {"chatroom_info": chatroom_info, "requester_ip": requester_ip}
                        )
                    
                    logger.info(f'[Follower {self.server_id}] Created chatroom {chatroom_id}, reported to Leader')

            if msg_type == "TAKE_OVER_CHATROOM":
                # Leader指示本server接管chatroom实例（从故障server迁移过来）
                chatroom_name = message.get("chatroom_name")
                old_chatroom_id = message.get("old_chatroom_id")
                original_group_members = message.get("original_group_members", {})
                
                logger.info(f'[Follower {self.server_id}] Taking over chatroom "{chatroom_name}" from old chatroom {old_chatroom_id}')
                
                # 使用ChatroomManager创建实际的chatroom
                room_info = self.chatroom_manager.create_room(chatroom_name)
                
                if room_info:
                    # 构造新chatroom信息
                    chatroom_id = f"{self.server_id}_{room_info['room_id']}"
                    chatroom_info = {
                        "chatroom_id": chatroom_id,
                        "name": chatroom_name,
                        "server_id": self.server_id,
                        "server_ip": self.network_manager.ip_local,
                        "port": room_info['port'],
                        "clients_count": 0
                    }
                    logger.info(f"[Follower {self.server_id}] Created chatroom {chatroom_id} to take over from old chatroom {old_chatroom_id}")
                    # todo: pulling historical chatting records from original group members
                    # attributes: old_chatroom_id, original_group_members

                    
                    # 回报给Leader
                    leader_ip = self.membership_list.get(self.leader_id)
                    if leader_ip:
                        self.network_manager.send_unicast(
                            leader_ip,
                            9001,
                            "CHATROOM_CREATED",
                            {"chatroom_info": chatroom_info}
                        )

                    
                    logger.info(f'[Follower {self.server_id}] Took over and created chatroom {chatroom_id}, reported to Leader')



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
                self.membership_manager.remove_group_member(removed_server_id, removed_group_id)
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
                    
                    # Close old connection, reconnect to new Leader
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
            elif msg_type == "GROUP_REASSIGN":
                moved_server_id = message.get("server_id")
                moved_server_ip = message.get("moved_server_ip")
                new_group_id = message.get("new_group_id")
                new_group_members = message.get("new_group_members", {})
                moved_server_id = int(moved_server_id) if isinstance(moved_server_id, str) else moved_server_id
                if moved_server_id == self.server_id:
                    self.membership_manager.set_group_info(new_group_id, new_group_members)
                elif new_group_id == self.membership_manager.group_id:
                    self.membership_manager.add_group_member(moved_server_id, moved_server_ip)
                logger.info(f'[Follower] Group reassignment: server {moved_server_id} moved to group {new_group_id}. Updated group members: {new_group_members}')
 
 
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
            
            # Close connection to old Leader (if converted from Follower)
            if old_role == TYPE_FOLLOWER:
                try:
                    # Get possible old leader_id from message
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
            
            # Notify all Followers to reconnect to new Leader
            self._notify_followers_new_leader()

            # Ensure heartbeat + fault detection are running in leader mode
            try:
                if not hasattr(self, "heartbeat") or self.heartbeat is None:
                    self.heartbeat = Heartbeat(self, interval=HEARTBEAT_INTERVAL)
                    self.heartbeat.start()
                # Wait a bit for followers to establish connections before first heartbeat
                logger.info(f"[Leader] Waiting for followers to connect...")
                time.sleep(1.5)  # Give followers time to connect
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
            # Set initial heartbeat timestamp to avoid immediate timeout
            self.leader_latest_heartbeat = time.time()
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
    
    def get_chatroom_info(self, server_id):
        chatrooms_name = None
        with self.chatroom_lock:
            chatrooms_name = {info["chatroom_id"] :info["name"] for info in self.chatroom_list.values() if info['server_id'] == server_id}
        return chatrooms_name


    def _select_server_for_chatroom(self):
        """Select server with fewest chatrooms to create (load balancing)"""
        # Count number of chatrooms owned by each server
        server_chatroom_count = {}
        
        # Initialize count for all servers to 0
        for server_id in self.membership_list.keys():
            server_chatroom_count[server_id] = 0
        
        # Count chatroom quantity for each server
        with self.chatroom_lock:
            for chatroom_info in self.chatroom_list.values():
                sid = chatroom_info.get('server_id')
                if sid in server_chatroom_count:
                    server_chatroom_count[sid] += 1
        
        # Select server with fewest chatrooms
        min_count = float('inf')
        selected_server = self.server_id
        
        for server_id, count in server_chatroom_count.items():
            if count < min_count:
                min_count = count
                selected_server = server_id
        
        logger.info(f"[Leader] Chatroom distribution: {server_chatroom_count}, selected: {selected_server}")
        return selected_server
    
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
        """Get current load information"""
        pass
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_percent = psutil.virtual_memory().percent
        memory_available = psutil.virtual_memory().available
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent
        }
    

