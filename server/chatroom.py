"""
This will generate a single chat room 
instance to manage clients connections and messages
"""
import threading
import socket
import queue

from common.vector_clock import VectorClock
from network.chatting_messenger import (
    send_tcp_message, receive_tcp_message,
    TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE
)


class ChatRoom:
    """A single chat room that manages client connections and messages"""
    
    def __init__(self, room_id, room_name, port, local_ip):
        """
        Args:
            room_id: Unique ID for this chatroom
            room_name: Display name of the chatroom
            port: TCP port to listen on
            local_ip: Local IP address to bind
        """
        self.room_id = room_id
        self.room_name = room_name
        self.port = port
        self.local_ip = local_ip
        
        # Client management
        self.clients = []  # List of client sockets
        self.client_info = {}  # {socket: {"user_id": xxx, "ip": xxx}}
        self.lock = threading.Lock()
        
        # Message queue for broadcasting
        self.msg_queue = queue.Queue()
        
        # Vector clock for causal ordering
        self.vector_clock = VectorClock()
        
        # Server socket
        self.server_socket = None
        self.running = False
    
    def start(self):
        """Start the chatroom (run in a separate thread)"""
        self.running = True
        
        # Create server socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        
        try:
            self.server_socket.bind((self.local_ip, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)
            
            print(f"[ChatRoom {self.room_id}] '{self.room_name}' listening on {self.local_ip}:{self.port}")
            
            # Start broadcast thread
            threading.Thread(target=self._broadcast_thread, daemon=True).start()
            
            # Accept clients
            while self.running:
                try:
                    client_socket, client_addr = self.server_socket.accept()
                    print(f"[ChatRoom {self.room_id}] Client connected from {client_addr}")
                    
                    with self.lock:
                        self.clients.append(client_socket)
                        self.client_info[client_socket] = {"ip": client_addr[0]}
                    
                    # Start client handler thread
                    threading.Thread(
                        target=self._handle_client, 
                        args=(client_socket, client_addr),
                        daemon=True
                    ).start()
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"[ChatRoom {self.room_id}] Accept error: {e}")
                        
        except Exception as e:
            print(f"[ChatRoom {self.room_id}] Failed to start: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the chatroom"""
        self.running = False
        
        # Close all client connections
        with self.lock:
            for client in self.clients:
                try:
                    client.close()
                except:
                    pass
            self.clients.clear()
            self.client_info.clear()
        
        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        
        print(f"[ChatRoom {self.room_id}] Stopped")
    
    def _handle_client(self, client_socket, client_addr):
        """Handle messages from a single client"""
        try:
            while self.running:
                message = receive_tcp_message(client_socket)
                
                if message is None:
                    print(f"[ChatRoom {self.room_id}] Client {client_addr} disconnected")
                    break
                
                msg_type = message.get('type')
                sender = message.get('sender')
                received_clock = message.get('vector_clock', {})
                content = message.get('content', '')
                
                print(f"[ChatRoom {self.room_id}] Received {msg_type} from {sender}: {content}")
                
                with self.lock:
                    if msg_type == TYPE_JOIN:
                        # Add user to vector clock
                        self.vector_clock.add_entry(sender)
                        self.vector_clock.merge(received_clock)
                        self.client_info[client_socket]["user_id"] = sender
                        print(f"[ChatRoom {self.room_id}] {sender} joined. Clock: {self.vector_clock.clock}")
                    
                    elif msg_type == TYPE_CHAT:
                        self.vector_clock.merge(received_clock)
                    
                    elif msg_type == TYPE_LEAVE:
                        print(f"[ChatRoom {self.room_id}] {sender} is leaving")
                
                # Put message in queue for broadcasting
                self.msg_queue.put((client_socket, message))
                
        except Exception as e:
            print(f"[ChatRoom {self.room_id}] Error handling client {client_addr}: {e}")
        finally:
            self._remove_client(client_socket)
    
    def _broadcast_thread(self):
        """Broadcast messages to all clients"""
        while self.running:
            try:
                sender_socket, message = self.msg_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            msg_type = message.get('type')
            
            with self.lock:
                for client in list(self.clients):
                    try:
                        if msg_type == TYPE_JOIN:
                            # For JOIN, send to everyone with server's clock
                            join_msg = message.copy()
                            join_msg['vector_clock'] = self.vector_clock.copy()
                            send_tcp_message(client, join_msg)
                        else:
                            # For CHAT/LEAVE, send to everyone except sender
                            if client != sender_socket:
                                send_tcp_message(client, message)
                    except Exception as e:
                        print(f"[ChatRoom {self.room_id}] Broadcast error: {e}")
                        self._remove_client(client)
            
            self.msg_queue.task_done()
    
    def _remove_client(self, client_socket):
        """Remove a client from the room"""
        with self.lock:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
            if client_socket in self.client_info:
                user_id = self.client_info[client_socket].get("user_id", "unknown")
                del self.client_info[client_socket]
                print(f"[ChatRoom {self.room_id}] Removed client {user_id}")
            try:
                client_socket.close()
            except:
                pass
    
    def get_client_count(self):
        """Return number of connected clients"""
        with self.lock:
            return len(self.clients)
    
    def get_info(self):
        """Return chatroom info for broadcasting"""
        return {
            "room_id": self.room_id,
            "room_name": self.room_name,
            "port": self.port,
            "clients": self.get_client_count()
        }

