"""
High-level flow (called by leader when a server is confirmed dead):
# 1. leader removes dead server from membership, notifies other servers
# 2. geting affected chatrooms and coresponding clients from dead server
# 3. reassign affected chatrooms to other active servers, and notify responsible servers
# 4. notify clients to connect to new servers
# 5. update membership accordingly (if needed)

Communication notes (placeholders marked TODO):
- Control messages between servers (leader <-> servers): use existing TCP long-lived connections (network.send_unicast).
- Client notifications: use existing client connection channel if leader knows client addresses, otherwise send server->server notifications so responsible server can notify its clients.
- Discovery/broadcast (optional): UDP broadcast/multicast for wide announcements (only for discovery, not routine).
"""

import time
import json
from typing import Dict, List, Optional
from utills.logger import get_logger
from server.config import ACTIVE, DEAD
from roles.leader import Leader

logger = get_logger("fault_discovery")

# todo: handle "SERVER_REMOVED" messages on other servers to update their membership
# todo: handle "TAKE_OVER_CHATROOM" : load historical messages from responsible group if needed

class ServerCrashDiscovery:
    def __init__(self, server : Leader):
        self.server = server

    def handle_dead_server(self, dead_server_id: str):
        logger.info(f"Handling dead server {dead_server_id}")
        # 1) remove dead server from responding membership maps
        try:
            self.server.membership.remove_server(dead_server_id)
            affected_group_id = self.server.membership.remove_server_from_group(dead_server_id)
            remained_group_members = self.server.membership.get_group_servers(affected_group_id)
            affected_chatrooms = self.server.membership.remove_chatrooms_of_server(dead_server_id)
        except Exception as e:
            logger.debug(f"failed to remove dead server {dead_server_id} from membership: {e}")
            return


        # 2) collect affected chatrooms and clients
        for affected_chatroom in affected_chatrooms:
            affected_clients = self.server.membership.get_clients_of_chatroom([affected_chatroom])
            if len(affected_clients) == 0:
                continue
            logger.info(f"Affected chatrooms: {affected_chatroom}, affected_clients: {len(affected_clients)}")

            # 3) reassign chatrooms
            new_server_id = self.server.membership.bind_chatroom(affected_chatroom, operation_type="rebind")
            # 4) notify new responsible server about chatroom
            if new_server_id:
                logger.info(f"Chatroom {affected_chatroom} reassigned to server {new_server_id}")
                try:
                    msg = {
                        "type": "TAKE_OVER_CHATROOM",
                        "message": {
                            "chatroom_id": affected_chatroom,
                            "from_dead_server": dead_server_id,
                            "group_mem": remained_group_members,
                            "timestamp": time.time()
                        }
                    }
                    # TODO: use TCP long-lived control channel to notify server (reliable)
                except Exception as e:
                    logger.debug(f"failed to notify server {new_server_id} for chatroom {affected_chatroom}: {e}")
            else:
                logger.debug(f"No available server to reassign chatroom {affected_chatroom}")
                continue


            # 5) notify affected clients to reconnect to new server
            for client_id in affected_clients:
                try:
                    new_addr = self.server.membership.servers[new_server_id]["address"]
                    notification = {
                        "type": "RECONNECT",
                        "chatroom_id": affected_chatroom,
                        "client_id": client_id,
                        "new_server": {"server_id": new_server_id, "address": new_addr},
                        "reason": "server_dead",
                        "timestamp": time.time()
                    }
                    # todo: leader notify client to reconnect
                except Exception as e:
                    logger.debug(f"failed to notify client {client_id}: {e}")

        # notify other servers about dead server
        msg = {
            "type": "SERVER_REMOVED",
            "message": {
                "server_id": dead_server_id,
                "group_id": affected_group_id,
                "timestamp": time.time()
            }
        }
        # todo : broadcast to all servers via TCP long-lived control channels


    def _get_client_addr(self, client_id: str, prev_server_id: str) -> Optional[str]:
        """
        Helper to get client's last-known address.
        """
        pass
        return self.server.membership.server_clients.get(prev_server_id, {}).get(client_id)

