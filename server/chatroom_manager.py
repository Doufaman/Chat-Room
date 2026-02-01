"""
This module manages chat rooms and client connections for a server.
Each server can have multiple chat rooms, each running in its own thread.
"""
import threading

from server.chatroom import ChatRoom


# Port calculation: BASE_PORT + (server_id * 100) + room_id
CHAT_PORT_BASE = 8000
CHAT_PORT_OFFSET = 100  # Each server gets 100 ports


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
        """Stop all chat rooms"""
        with self.lock:
            for room_id, room in list(self.rooms.items()):
                room.stop()
            self.rooms.clear()
            self.room_threads.clear()
            print("[ChatroomManager] All rooms stopped")
    
    def get_server_chat_info(self):
        """
        Get this server's chat info for HEARTBEAT_ACK.
        
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