# bind and manage the relationship between client, server, chatroom and replication_group

from typing import Dict, List, Optional
import time
from utills.logger import get_logger
from server.config import MAX_SERVERS_PER_GROUP, ACTIVE, SUSPECT, DEAD

logger = get_logger("membership")

# todo: after server resgister, notify other servers about new server(incluing group id)
# todo: after server resgister, notify server about its group id, group members
# todo: after chatroom bind, notify responsible server about new chatroom

# in some situation, the identity of server will change, so use same class

class MembershipManager():
    """
    MembershipManager maintains the cluster view.
    It does NOT perform communication.
    It only updates and queries membership state.
    """

    def __init__(self, is_leader: bool):
        self.is_leader = is_leader
        # chatroom_id -> [client_id]
        self.chatroom_clients: Dict[str, List[int]] = {}
        # client_info
        self.clients: Dict[int, Dict] = {}

        self.group_id: str = ""  # assigned group_id
        self.group_members: Dict[int, str] = {}  # other servers in the group

        self.chatrooms: List[str] = []  # chatrooms this server is responsible for

        # server_id -> {
        #   status,
        #   last_heartbeat_ts,
        #   load_info {
        #     cpu_percent,
        #     memory_percent},
        #   address
        # }
        self.servers: Dict[int, Dict] = {} # owner: leader

        # group_id -> [server_id]
        self.group_servers: Dict[str, List[int]] = {} # owner: leader

        # server_id -> group_id
        self.server_groups: Dict[int, str] = {} # owner: leader

        # server_id -> [chatroom_id]
        self.server_chatrooms: Dict[int, List[str]] = {} # owner: leader

        # chatroom_id -> server_id
        self.chatrooms: Dict[str, int] = {} # owner: leader

    def initialize_for_leader(self, is_leader, server_info):
        """
        Initialize membership for leader with its own server info.
        """
        self.is_leader = is_leader
        if is_leader:
            self.servers[server_info["server_id"]] = {
                "status": ACTIVE,
                "last_heartbeat_ts": time.time(),
                "load_info": server_info.get("load_info", {}),
                "address": server_info.get("address", "")
            }
            group_id, existed_members = self.assign_group(server_info["server_id"])
            self.group_id = group_id
            self.group_members = existed_members
            logger.info(f"Leader initialized with server info: {server_info}")

    # ------------------------------------------------------------------
    # Server lifecycle management
    # ------------------------------------------------------------------

    def add_server(self, server_id: int, address: str, load_info: dict = None):
        """
        Add a new server to membership.
        Leader only.
        """
        pass
        
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return
        
        # avoid duplicate add
        if server_id in self.servers:
            logger.warning(f"server {server_id} already exists")
            return
        
        # add server data
        self.servers[server_id] = {
            "status": ACTIVE,
            "last_heartbeat_ts": time.time(),
            "load_info": load_info if load_info is not None else {},
            "address": address
        }
        # initiate chatroom info for server
        self.server_chatrooms[server_id] = []
        logger.info(f"server added: {server_id}")
        
    def remove_server(self, server_id: int):
        """
        Remove a server completely from membership.
        Leader only.
        """
        pass

        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return
        if not server_id in self.servers:
            logger.warning(f"server {server_id} is not existed")
            return  

        # delete server from servers dict
        del self.servers[server_id]

        logger.info(f"server removed: {server_id}")

    def update_server_status(self, server_id: int, status: str):
        """
        Update server status: ACTIVE / SUSPECT / DEAD.
        """
        pass

        if server_id not in self.servers:
            logger.warning(f"server {server_id} does not exist")
            return

        if status not in (
            ACTIVE,
            SUSPECT,
            DEAD,
        ):
            logger.error(f"invalid server status: {status}")
            return

        old_status = self.servers[server_id]["status"]
        self.servers[server_id]["status"] = status

        logger.info(
            f"server {server_id} status changed: "
            f"{old_status} -> {status}"
        )      

    def get_serrver_status(self, server_id: int) -> str:
        """
        Get server status.
        """
        pass
        if not server_id in self.servers:
            logger.warning(f"server {server_id} is not existed")
            return ""
        return self.servers[server_id]["status"]

    def update_heartbeat(self, server_id: int, timestamp: float):
        """
        Update last heartbeat timestamp of a server.
        """
        pass
        if not server_id in self.servers:
            logger.warning(f"server {server_id} is not existed")
            return 
        self.servers[server_id]["last_heartbeat_ts"] = timestamp

        

    def update_server_load(self, server_id: int, load_info: dict):
        """
        Update server load information.
        """
        pass
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return
        if not server_id in self.servers:
            logger.warning(f"server {server_id} is not existed")
            return  
        
        self.servers[server_id]["load_info"] = load_info

        

    def get_active_servers(self) -> Dict[int, float]:
        """
        Return mapping of ACTIVE server_id -> last_heartbeat_ts.
        """
        pass
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return {}

        active_servers: Dict[int, float] = {}

        for server_id, info in self.servers.items():
            if info.get("status") == ACTIVE:
                active_servers[server_id] = info.get("last_heartbeat_ts")
        return active_servers

    # ------------------------------------------------------------------
    # Group (replication group) management
    # ------------------------------------------------------------------

    def assign_group(self, server_id: int):
        """
        Assign a server to a replication group.
        (acc to load balancing policy)
        Return assigned group_id.
        Leader only.
        """
        pass
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return "", {}
        # assign group according to the number of servers and the sum of load in each group
        group_id = None
        min_load = float("inf")
        existed_members: Dict[int, str] = {}

        for g_id, servers in self.group_servers.items():
            if len(servers) < MAX_SERVERS_PER_GROUP:
                total_load = sum(
                    self.servers[s_id]["load_info"]["cpu_percent"] + self.servers[s_id]["load_info"]["memory_percent"] for s_id in servers
                )
                if total_load < min_load:
                    min_load = total_load
                    group_id = g_id

        if not group_id:
            # create a new group
            group_id = f"group_{len(self.group_servers)}"
            self.group_servers[group_id] = []

        existed_members_id = self.group_servers[group_id]
        for sid in existed_members_id:
            existed_members[sid] = self.servers[sid]["address"]
        self.group_servers[group_id].append(server_id)
        self.server_groups[server_id] = group_id

        logger.info(f"server {server_id} assigned to group {group_id}")

        return group_id, existed_members

    def get_group_servers(self, group_id: str) -> Dict[int, str]:
        """
        Get all servers in a group.
        """
        pass
        if group_id not in self.group_servers:
            logger.warning(f"group {group_id} does not exist")
            return {}
        return {sid: self.servers[sid]["address"] for sid in self.group_servers[group_id]}

    def remove_server_from_group(self, server_id: int) -> Optional[str]:
        """
        Remove server from its group.
        """
        pass
        if server_id not in self.server_groups:
            logger.warning(f"server {server_id} is not assigned to any group")
            return None

        group_id = self.server_groups[server_id]
        self.group_servers[group_id].remove(server_id)
        del self.server_groups[server_id]
        return group_id

    def get_server_group(self, server_id: int) -> Optional[str]:
        """
        Get the group_id of a server.
        """
        pass
        if server_id not in self.server_groups:
            logger.warning(f"server {server_id} is not assigned to any group")
            return None

        return self.server_groups[server_id]
    
    def set_group_info(self, group_id: str, group_members: Dict[int, str]):
        """
        Set group information.
        """
        pass
        self.group_id = group_id
        self.group_members = group_members

    def add_group_member(self, server_id: int, server_ip: str):
        """
        Add a server to group members.
        """
        pass
        if server_id not in self.group_members:
            self.group_members[server_id] = server_ip
        

    def remove_group_member(self, server_id: int):
        """
        Remove a server from group members.
        """
        pass
        if server_id in self.group_members:
            del self.group_members[server_id]

    def bind_chatroom(self, chatroom_id: str):
        """
        Bind a chatroom to this server.
        """
        pass
        if chatroom_id not in self.chatrooms:
            self.chatrooms.append(chatroom_id)

    # ------------------------------------------------------------------
    # Chatroom management
    # ------------------------------------------------------------------

    def bind_chatroom(self, chatroom_id: str, operation_type: str) -> Optional[int]:
        """
        Bind a chatroom to a server.
        1. "first": first bind when chatroom is created.
        2. "rebind": rebind when origin server is dead.
        (according to load balancing policy): active & min(cup + chatroom_num*0.1)
        Leader only.
        """
        pass
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return None
        
        # avoid duplicate bind for "first" operation
        if operation_type == "first" and chatroom_id in self.chatrooms:
            logger.warning(f"chatroom {chatroom_id} is already bound to server {self.chatrooms[chatroom_id]}")
            return self.chatrooms[chatroom_id]
        min_load = float("inf")
        min_chatroom_num = float("inf")
        selected_server: Optional[int] = None
        # bind chatroom to server: choose server based on load
        for srv_id in self.servers:
            if self.servers[srv_id]["status"] != ACTIVE:
                continue
            load_info = self.servers[srv_id]["load_info"]
                    #   load_info {
                    #     cpu_percent,
                    #     memory_percent},
            chatroom_num = len(self.server_chatrooms.get(srv_id, []))
            load_metric = load_info.get("cpu_percent", 0) + load_info.get("memory_percent", 0) + chatroom_num * 0.1  # simple load metric
            if load_metric <= min_load and chatroom_num < min_chatroom_num:
                min_load = load_metric
                min_chatroom_num = chatroom_num
                selected_server = srv_id 

        if not selected_server:
            logger.warning(f"no active server available for chatroom {chatroom_id}")
            return None

        self.chatrooms[chatroom_id] = selected_server
        if selected_server not in self.server_chatrooms:
            self.server_chatrooms[selected_server] = []
        self.server_chatrooms[selected_server].append(chatroom_id)
        logger.info(f"chatroom {chatroom_id} bound to server {selected_server}")

        return selected_server


    def get_chatroom_server(self, chatroom_id: str) -> Optional[int]:
        """
        Get server responsible for a chatroom.
        """
        pass
        return self.chatrooms.get(chatroom_id)
    


    def remove_chatrooms_of_server(self, server_id: int) -> List[str]:
        """
        Remove all chatrooms bound to a server.
        Return affected chatroom_ids.
        """
        pass
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return []
        affected_chatrooms = self.server_chatrooms.get(server_id, [])
        if server_id in self.server_chatrooms:
            del self.server_chatrooms[server_id]
        return affected_chatrooms



    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    def add_client(self, client_id: int, client_info: dict):
        """
        Add a client to the membership view.
        Leader only.
        """
        pass
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return
        if client_id in self.clients:
            logger.warning(f"client {client_id} already exists")
            return
        self.clients[client_id] = client_info
        logger.info(f"client added: {client_id}")

    def remove_client(self, client_id: int):
        """
        Remove client from membership view.
        """
        pass
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return
        if client_id not in self.clients:
            logger.warning(f"client {client_id} does not exist")
            return
        del self.clients[client_id]
        logger.info(f"client removed: {client_id}")

    def get_clients_of_chatroom(self, chatroom_id: str) -> List[int]:
        """
        Get all clients in a chatroom.
        """
        pass
        return self.chatroom_clients.get(chatroom_id, [])










