"""
High-level flow (called by leader when a server is confirmed dead):
# 1. leader removes dead server from membership_manager, notifies other servers
#  geting affected chatrooms and coresponding clients from dead server
# 3. reassign affected chatrooms to other active servers, and notify responsible servers
# 4. notify clients to connect to new servers
# 5. update membership_manager accordingly (if needed)

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

logger = get_logger("fault_discovery")

# todo: handle "SERVER_REMOVED" messages on other servers to update their membership_manager
# todo: handle "TAKE_OVER_CHATROOM" : load historical messages from responsible group if needed

class ServerCrashDiscovery:
    def __init__(self, server):
        self.server = server

    def handle_dead_server(self, dead_server_id: str):
        logger.info(f"Handling dead server {dead_server_id}")
      # 1) remove dead server from responding membership_manager maps
        try:
            # remove from group list:
            affected_group_id = self.server.membership_manager.remove_server_from_group(dead_server_id)
            original_group_members = self.server.membership_manager.get_group_servers(affected_group_id)
            self.server.membership_manager.remove_group_member(affected_group_id, dead_server_id)

            self.server.membership_manager.remove_server(dead_server_id)
            membership = getattr(self.server, "membership_list", None)
            if isinstance(membership, dict):
                membership.pop(dead_server_id, None)
            else:
                logger.warning(f"server.membership_list missing or not a dict; cannot pop {dead_server_id}")
            
        #     remained_group_members = self.server.membership_manager.get_group_servers(affected_group_id)
        #     affected_chatrooms = self.server.membership_manager.remove_chatrooms_of_server(dead_server_id)
        except Exception as e:
            logger.debug(f"failed to remove dead server {dead_server_id} from membership_manager: {e}")
            return
        
        # 5)notify other servers about dead server
        for sid, sip in self.server.membership_list.items():
            if sid != self.server.server_id:
                self.server.network_manager.send_unicast(
                    sip,
                    9001,
                    "SERVER_REMOVED",
                    {"server_id": dead_server_id, 
                    "group_id": affected_group_id}
                    # new_chatroom assignment(server_id, chatroom_id list)
                )


        # 6) check and adjust group assignments if needed
        self.check_and_repair_orphan_groups()

         # 7) reassign chatrooms of the dead server to other servers
        self.reassign_chatroom(dead_server_id, original_group_members)

    def check_and_repair_orphan_groups(self):
        repair_result = self.server.membership_manager.check_and_repair_orphan_groups()
        logger.info(f"current group_id: {self.server.membership_manager.group_id}, group_members: {self.server.membership_manager.group_members}")
        if repair_result is not None:
            moved_server_id, moved_server_ip, new_group_id, new_group_existing_members = repair_result
            logger.info(f"Repaired orphan group: moved server {moved_server_id} to {new_group_id}")
            # notify affected servers about group chang
            notify_list = list(new_group_existing_members.keys()) + [moved_server_id]
            for sid in notify_list:
                if sid != self.server.server_id:
                    sip = self.server.membership_list.get(sid)
                    if sip:
                        self.server.network_manager.send_unicast(
                            sip,
                            9001,
                            "GROUP_REASSIGN",
                            {"server_id": moved_server_id,
                             "moved_server_ip": moved_server_ip,
                             "new_group_id": new_group_id,
                             "new_group_members": new_group_existing_members}
                        )
                    else:
                        logger.warning(f"Cannot find IP for server {sid} to notify about group reassignment")
                else:
                    self.server.membership_manager.update_group_info(moved_server_id, new_group_id, new_group_existing_members, self.server.server_id)  # update self group assignment
                    logger.info(f"current group_id: {self.server.membership_manager.group_id}, group_members: {self.server.membership_manager.group_members}")


    def reassign_chatroom(self, dead_server_id, original_group_members = None):
        new_assignment = {}

       # get affected chatrooms and reassign to other servers
        # 1) get the number of affected chatrooms;
        chatrooms_info = self.server.get_chatroom_info(dead_server_id)
        logger.info(f"Dead server {dead_server_id} had chatrooms: {chatrooms_info}")
        
        if chatrooms_info is not None and len(chatrooms_info) > 0:
            all_chatroomids = list(chatrooms_info.keys())
            # leader delete chatrooms from the chatromm_list
            for chatroom_id in all_chatroomids:
                with self.server.chatroom_lock:
                    if chatroom_id in self.server.chatroom_list:
                        del self.server.chatroom_list[chatroom_id]
                        logger.info(f"Leader {self.server.server_id} Deleted chatroom {chatroom_id} of dead server {dead_server_id} from chatroom_list")
                    else:
                        logger.warning(f"Chatroom {chatroom_id} of dead server {dead_server_id} not found in chatroom_list during deletion")
            logger.info(f"server {self.server.server_id} current chatroom_list after deletion: {self.server.chatroom_list}")
            # 2) notify all the servers to delete chatrooms of the dead server
            for sid, sip in self.server.membership_list.items():
                if sid != self.server.server_id:
                    self.server.network_manager.send_unicast(
                        sip,
                        9001,
                        "CHATROOM_DELETED",
                        {"server_id": dead_server_id, 
                         "chatroom_ids": all_chatroomids}
                    )
            # 3) for each affected chatroom, assign to a new server
            for old_chatroom_id, chatroom_name in chatrooms_info.items():
                new_server_id = self.server._select_server_for_chatroom()
                new_assignment[new_server_id] = old_chatroom_id
                logger.info(f"Reassigning chatroom '{chatroom_name}' of dead server {dead_server_id} to new server {new_server_id}")
                # 3.1) if new server is leader, create chatroom, update chatroomlist, notify all the servers
                if new_server_id == self.server.server_id:
                    room_info = self.server.chatroom_manager.create_room(chatroom_name)
                    if room_info:
                        chatroom_id = f"{self.server.server_id}_{room_info['room_id']}"
                        chatroom_info = {
                            "chatroom_id": chatroom_id,
                            "name": chatroom_name,
                            "server_id": self.server.server_id,
                            "server_ip": self.server.network_manager.ip_local,
                            "port": room_info['port'],
                            "clients_count": 0
                        }
                        
                        # 更新本地列表
                        with self.server.chatroom_lock:
                            self.server.chatroom_list[chatroom_id] = chatroom_info
                        logger.info(f"Leader {self.server.server_id} Added new chatroom {chatroom_id} to chatroom_list")
                        
                        # 广播给所有server
                        for server_id, server_ip in self.server.membership_list.items():
                            if server_id != self.server.server_id:
                                self.server.network_manager.send_unicast(
                                    server_ip,
                                    9001,
                                    "NEW_CHATROOM",
                                    {"chatroom_info": chatroom_info}
                                )
                        
                        # 通知请求的客户端（UDP广播）: todo待确认
                        self.network_manager.send_broadcast(
                            "CHATROOM_CREATED",
                            {"chatroom_info": chatroom_info}
                        )

                # 3.2) if new server is follower, notify the server to create chatroom
                else:
                    logger.info(f"Notifying follower server {new_server_id} to take over chatroom '{chatroom_name}'")
                    new_server_ip = self.server.membership_list.get(new_server_id)
                    if new_server_ip:
                        self.server.network_manager.send_unicast(
                            new_server_ip,
                            9001,
                            "TAKE_OVER_CHATROOM",
                            {"chatroom_name": chatroom_name,
                             "old_chatroom_id": old_chatroom_id,
                             "original_group_members": original_group_members
                            }
                        )
                    else:
                        logger.warning(f"Cannot find IP for new server {new_server_id} to notify about chatroom takeover")

        return new_assignment


 


    def _get_client_addr(self, client_id: str, prev_server_id: str) -> Optional[str]:
        """
        Helper to get client's last-known address.
        """
        pass
        return self.server.membership_manager.server_clients.get(prev_server_id, {}).get(client_id)

