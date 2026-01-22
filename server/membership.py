# bind and manage the relationship between client, server, chatroom and replication_group

from typing import Dict, List, Optional
import time
from utills.logger import get_logger

logger = get_logger("membership")

class ServerStatus:
    ACTIVE = "ACTIVE"
    SUSPECT = "SUSPECT"
    DEAD = "DEAD"


class MembershipManager:
    """
    MembershipManager maintains the cluster view.
    It does NOT perform communication.
    It only updates and queries membership state.
    """

    def __init__(self, is_leader: bool):
        self.is_leader = is_leader

        # server_id -> {
        #   status,
        #   last_heartbeat_ts,
        #   load_info,
        #   address
        # }
        self.servers: Dict[str, Dict] = {}

        # group_id -> [server_id]
        self.groups: Dict[str, List[str]] = {}

        # server_id -> [client_id]
        self.server_clients: Dict[str, List[str]] = {}

        # chatroom_id -> server_id
        self.chatrooms: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Server lifecycle management
    # ------------------------------------------------------------------

    def add_server(self, server_id: str, address: str, load_info: Optional[dict] = None):
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
            "status": ServerStatus.ACTIVE,
            "last_heartbeat_ts": time.time(),
            "load_info": load_info if load_info is not None else {},
            "address": address
        }
        # initiate client info for server
        self.server_clients[server_id] = []
        logger.info(f"server added: {server_id}")
        
    def remove_server(self, server_id: str):
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

        # 1. delete server from servers dict
        del self.servers[server_id]
        # 2. delete server-clients mapping   
        if server_id in self.server_clients:
            del self.server_clients[server_id]  

        logger.info(f"server removed: {server_id}")

    def update_server_status(self, server_id: str, status: str):
        """
        Update server status: ACTIVE / SUSPECT / DEAD.
        """
        pass

        if server_id not in self.servers:
            logger.warning(f"server {server_id} does not exist")
            return

        if status not in (
            ServerStatus.ACTIVE,
            ServerStatus.SUSPECT,
            ServerStatus.DEAD,
        ):
            logger.error(f"invalid server status: {status}")
            return

        old_status = self.servers[server_id]["status"]
        self.servers[server_id]["status"] = status

        logger.info(
            f"server {server_id} status changed: "
            f"{old_status} -> {status}"
        )      

    def update_heartbeat(self, server_id: str):
        """
        Update last heartbeat timestamp of a server.
        """
        pass
        if not server_id in self.servers:
            logger.warning(f"server {server_id} is not existed")
            return 
        self.servers[server_id]["last_heartbeat_ts"] = time.time()

        

    def update_server_load(self, server_id: str, load_info: dict):
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

        

    def get_active_servers(self) -> List[str]:
        """
        Return list of ACTIVE server_ids.
        """
        pass
        if not self.is_leader:
            logger.error("illegal operation (not leader)")
            return []

        active_servers = []

        for server_id, info in self.servers.items():
            if info.get("status") == ServerStatus.ACTIVE:
                active_servers.append(server_id)

        return active_servers

    # ------------------------------------------------------------------
    # Group (replication group) management
    # ------------------------------------------------------------------

    def assign_group(self, server_id: str) -> str:
        """
        Assign a server to a replication group.
        Return assigned group_id.
        Leader only.
        """
        pass

    def get_group_servers(self, group_id: str) -> List[str]:
        """
        Get all servers in a group.
        """
        pass

    def remove_server_from_group(self, server_id: str):
        """
        Remove server from its group.
        """
        pass

    def get_server_group(self, server_id: str) -> Optional[str]:
        """
        Get the group_id of a server.
        """
        pass

    # ------------------------------------------------------------------
    # Chatroom management
    # ------------------------------------------------------------------

    def bind_chatroom(self, chatroom_id: str, server_id: str):
        """
        Bind a chatroom to a server.
        Leader only.
        """
        pass

    def rebind_chatroom(self, chatroom_id: str, new_server_id: str):
        """
        Rebind chatroom to a new server (e.g., after crash).
        Leader only.
        """
        pass

    def get_chatroom_server(self, chatroom_id: str) -> Optional[str]:
        """
        Get server responsible for a chatroom.
        """
        pass

    def remove_chatrooms_of_server(self, server_id: str) -> List[str]:
        """
        Remove all chatrooms bound to a server.
        Return affected chatroom_ids.
        """
        pass

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    def add_client_to_server(self, server_id: str, client_id: str):
        """
        Record that a client is connected to a server.
        Leader only.
        """
        pass

    def remove_client_from_server(self, server_id: str, client_id: str):
        """
        Remove client from server-client mapping.
        """
        pass

    def get_server_clients(self, server_id: str) -> List[str]:
        """
        Get all clients connected to a server.
        """
        pass

    # ------------------------------------------------------------------
    # Failure handling support (query helpers)
    # ------------------------------------------------------------------

    def get_suspect_servers(self) -> List[str]:
        """
        Return list of servers marked as SUSPECT.
        """
        pass

    def get_dead_servers(self) -> List[str]:
        """
        Return list of servers marked as DEAD.
        """
        pass

    def select_server_for_chatroom(self) -> Optional[str]:
        """
        Select a server for a new chatroom based on load.
        Leader only.
        """
        pass

    def select_replacement_server(self, failed_server_id: str) -> Optional[str]:
        """
        Select a new server to replace a failed server.
        Leader only.
        """
        pass

    # ------------------------------------------------------------------
    # View export / import (for leader crash or sync)
    # ------------------------------------------------------------------

    def export_view(self) -> dict:
        """
        Export full membership view (for leader crash recovery).
        """
        pass

    def import_view(self, view: dict):
        """
        Import membership view (used by new leader).
        """
        pass
