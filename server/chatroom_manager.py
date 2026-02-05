"""
This module manages chat rooms and client connections for a server.
Each server can have multiple chat rooms, each running in its own thread.
Each server has ONE ChatroomManager
ChatroomManager manages multiple ChatRoom instances
Only Leader's ChatroomManager listens for Client discovery requests
ElectionManager calls get_chatroom_info_callback() during heartbeat
"""
import threading
import socket
import json

from server.chatroom import ChatRoom


# Port calculation: BASE_PORT + (server_id * 100) + room_id
CHAT_PORT_BASE = 8000
CHAT_PORT_OFFSET = 100  # Each server gets 100 ports

# Discovery port (Leader listens here for client requests)
PORT_CLIENT_DISCOVERY = 9005


class ChatroomManager:
    """
    Manages multiple chat rooms for a single server.
    
    Port allocation:
        Server 1, Room 1 → 8000 + 100 + 1 = 8101
        Server 1, Room 2 → 8000 + 100 + 2 = 8102
        Server 2, Room 1 → 8000 + 200 + 1 = 8201
    """
    
    def __init__(self, server_id, local_ip):
        """
        Args:
            server_id: This server's ID
            local_ip: Local IP address to bind chat rooms
        """
        self.server_id = server_id
        self.local_ip = local_ip
        
        # Chat rooms: {room_id: ChatRoom}
        self.rooms = {}
        self.room_threads = {}  # {room_id: Thread}
        self.lock = threading.Lock()
        
        # Next room ID to assign
        self.next_room_id = 1
        
        # === Leader-only: aggregated chatroom list from all servers ===
        self.all_servers_chatrooms = []  # [{server_id, server_ip, chatrooms}, ...]
        self.all_servers_lock = threading.Lock()
        
        # === Discovery listener (Leader only) ===
        self.discovery_running = False
        self.discovery_thread = None
    
    def _calculate_port(self, room_id):
        """Calculate port for a room based on server_id and room_id"""
        return CHAT_PORT_BASE + (self.server_id % 100) * CHAT_PORT_OFFSET + room_id
    
    def create_room(self, room_name=None):
        """
        Create a new chat room.
        
        Args:
            room_name: Optional name for the room (default: "Room X")
        
        Returns:
            dict: Room info {room_id, room_name, port} or None on failure
        """
        with self.lock:
            room_id = self.next_room_id
            self.next_room_id += 1
            
            if room_name is None:
                room_name = f"Room {room_id}"
            
            port = self._calculate_port(room_id)
            
            # Create ChatRoom instance
            room = ChatRoom(room_id, room_name, port, self.local_ip)
            self.rooms[room_id] = room
            
            # Start room in a new thread
            thread = threading.Thread(target=room.start, daemon=True)
            thread.start()
            self.room_threads[room_id] = thread
            
            print(f"[ChatroomManager] Created room '{room_name}' (ID: {room_id}, Port: {port})")
            
            return room.get_info()
    
    def delete_room(self, room_id):
        """
        Delete a chat room.
        
        Args:
            room_id: ID of the room to delete
        
        Returns:
            bool: True if deleted, False if not found
        """
        with self.lock:
            if room_id not in self.rooms:
                print(f"[ChatroomManager] Room {room_id} not found")
                return False
            
            room = self.rooms[room_id]
            room.stop()
            
            del self.rooms[room_id]
            if room_id in self.room_threads:
                del self.room_threads[room_id]
            
            print(f"[ChatroomManager] Deleted room {room_id}")
            return True
    
    def get_room(self, room_id):
        """Get a specific room by ID"""
        with self.lock:
            return self.rooms.get(room_id)
    
    def get_all_room_info(self):
        """
        Get info for all rooms (for Leader to broadcast).
        
        Returns:
            list: List of room info dicts
        """
        with self.lock:
            return [room.get_info() for room in self.rooms.values()]
    
    def get_total_client_count(self):
        """Get total number of clients across all rooms"""
        with self.lock:
            return sum(room.get_client_count() for room in self.rooms.values())
    
    def get_room_count(self):
        """Get number of rooms"""
        with self.lock:
            return len(self.rooms)
    
    def stop_all(self):
        """Stop all chat rooms and discovery listener"""
        self.stop_discovery_listener()
        with self.lock:
            for room_id, room in list(self.rooms.items()):
                room.stop()
            self.rooms.clear()
            self.room_threads.clear()
            print("[ChatroomManager] All rooms stopped")
    
    def get_server_chat_info(self):
        """
        Get this server's chat info for HEARTBEAT_ACK.
        This is the CALLBACK function for ElectionManager.
        
        Returns:
            dict: {
                "server_id": xxx,
                "server_ip": xxx,
                "chatrooms": [...]
            }
        """
        return {
            "server_id": self.server_id,
            "server_ip": self.local_ip,
            "chatrooms": self.get_all_room_info()
        }
    
    # =================================================================
    #  Leader-only: Aggregate chatroom info from followers
    # =================================================================
    
    def update_all_servers_chatrooms(self, servers_list):
        """
        Called by ElectionManager when it aggregates chatroom info.
        
        Args:
            servers_list: List of {server_id, server_ip, chatrooms}
        """
        with self.all_servers_lock:
            self.all_servers_chatrooms = servers_list
    
    def get_all_servers_chatrooms(self):
        """Get the aggregated chatroom list (Leader only)"""
        with self.all_servers_lock:
            return list(self.all_servers_chatrooms)
    
    # =================================================================
    #  Leader-only: Discovery Listener for Client requests
    # =================================================================
    
    def start_discovery_listener(self):
        """
        Start listening for Client discovery requests (Leader only).
        Clients send REQUEST_CHATROOMS, Leader responds with CHATROOM_LIST.
        """
        if self.discovery_running:
            return
        
        self.discovery_running = True
        self.discovery_thread = threading.Thread(
            target=self._discovery_listener_loop, 
            daemon=True
        )
        self.discovery_thread.start()
        print(f"[ChatroomManager] Discovery listener started on port {PORT_CLIENT_DISCOVERY}")
    
    def stop_discovery_listener(self):
        """Stop the discovery listener"""
        self.discovery_running = False
    
    def _discovery_listener_loop(self):
        """Listen for Client REQUEST_CHATROOMS on UDP"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.settimeout(1.0)
        
        try:
            sock.bind(('0.0.0.0', PORT_CLIENT_DISCOVERY))
            
            while self.discovery_running:
                try:
                    data, addr = sock.recvfrom(4096)
                    message = json.loads(data.decode('utf-8'))
                    
                    msg_type = message.get('msg_type')
                    if msg_type == 'REQUEST_CHATROOMS':
                        client_port = message.get('message', {}).get('client_port', PORT_CLIENT_DISCOVERY)
                        print(f"[ChatroomManager] Client {addr[0]}:{client_port} requesting chatroom list")
                        
                        # Respond with aggregated chatroom list
                        response = {
                            'msg_type': 'CHATROOM_LIST',
                            'message': {
                                'servers': self.get_all_servers_chatrooms()
                            },
                            'sender_ip': self.local_ip
                        }
                        sock.sendto(
                            json.dumps(response).encode('utf-8'),
                            (addr[0], client_port)
                        )
                        print(f"[ChatroomManager] Sent CHATROOM_LIST to {addr[0]}:{client_port}")
                        
                except socket.timeout:
                    continue
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    if self.discovery_running:
                        print(f"[ChatroomManager] Discovery error: {e}")
        finally:
            sock.close()
            print("[ChatroomManager] Discovery listener stopped")