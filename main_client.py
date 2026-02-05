"""
Chat Client - Connects to a chat room server:
- Discover available servers and chatrooms via Leader
- Connect to selected chatroom
- Send and receive messages with causal ordering
"""
import socket
import threading
import sys
import os
import json

from network.chatting_messenger import (
    send_tcp_message, receive_tcp_message, create_chat_message,
    TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, safe_print
)
from common.vector_clock import VectorClock

# Discovery port (must match ChatroomManager.PORT_CLIENT_DISCOVERY)
PORT_DISCOVERY = 9005
DISCOVERY_TIMEOUT = 5.0


class ChatClient:
    """Chat client with causal ordering support"""
    
    def __init__(self, user_id):
        self.user_id = user_id
        self.vector_clock = VectorClock(user_id)
        self.socket = None
        self.running = False
        self.lock = threading.Lock()
        self.hold_back_queue = []  # For causal ordering
    
    def discover_chatrooms(self):
        """
        Discover available chatrooms by querying the Leader.
        
        Returns:
            list: Server chatroom info, or None if discovery failed
        """
        print("\n[Discovery] Searching for available chatrooms...")
        
        # Create UDP socket for discovery
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_socket.settimeout(DISCOVERY_TIMEOUT)
        
        try:
            # Bind to receive response
            udp_socket.bind(('', 0))
            local_port = udp_socket.getsockname()[1]
            
            # Send discovery request (broadcast to Leader's discovery port)
            request = {
                'msg_type': 'REQUEST_CHATROOMS',
                'message': {'client_port': local_port},
                'sender_ip': '0.0.0.0'
            }
            udp_socket.sendto(
                json.dumps(request).encode('utf-8'),
                ('<broadcast>', PORT_DISCOVERY)
            )
            print(f"[Discovery] Sent REQUEST_CHATROOMS broadcast to port {PORT_DISCOVERY}")
            
            # Wait for response
            try:
                data, addr = udp_socket.recvfrom(4096)
                response = json.loads(data.decode('utf-8'))
                
                msg_type = response.get('msg_type')
                if msg_type == 'CHATROOM_LIST':
                    servers = response.get('message', {}).get('servers', [])
                    print(f"[Discovery] Received chatroom list from Leader {addr[0]}")
                    return servers
                    
            except socket.timeout:
                print("[Discovery] Timeout - No Leader responded")
                return None
                
        except Exception as e:
            print(f"[Discovery] Error: {e}")
            return None
        finally:
            udp_socket.close()
    
    def display_chatrooms(self, servers):
        """Display available chatrooms to user"""
        print("\n" + "=" * 60)
        print("Available Chatrooms:")
        print("=" * 60)
        
        if not servers:
            print("  No chatrooms available.")
            return
        
        for server in servers:
            server_id = server.get('server_id', '?')
            server_ip = server.get('server_ip', '?')
            chatrooms = server.get('chatrooms', [])
            
            if chatrooms:
                print(f"\nServer {server_id} ({server_ip}):")
                for room in chatrooms:
                    room_name = room.get('room_name', 'Unknown')
                    room_port = room.get('port', '?')
                    clients = room.get('clients', 0)
                    print(f"  - {room_name} ({clients} clients) → Port {room_port}")
            else:
                print(f"\nServer {server_id} ({server_ip}): No chatrooms")
        
        print("=" * 60)
    
    def prompt_connection(self):
        """
        Prompt user to enter server IP and port.
        
        Returns:
            tuple: (ip, port) or None if user wants to refresh
        """
        print("\nEnter connection details (or 'r' to refresh, 'q' to quit):")
        
        ip = input("Server IP: ").strip()
        if ip.lower() == 'r':
            return 'refresh'
        if ip.lower() == 'q':
            return None
        
        port_str = input("Port: ").strip()
        if port_str.lower() == 'r':
            return 'refresh'
        if port_str.lower() == 'q':
            return None
        
        try:
            port = int(port_str)
            return (ip, port)
        except ValueError:
            print("[Error] Invalid port number")
            return 'refresh'
    
    def connect(self, server_ip, server_port):
        """
        Connect to a chatroom server.
        
        Args:
            server_ip: Server IP address
            server_port: Server port
        
        Returns:
            bool: True if connected successfully
        """
        print(f"\n[Client] Connecting to {server_ip}:{server_port}...")
        
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(10.0)
            self.socket.connect((server_ip, server_port))
            self.socket.settimeout(None)
            
            print(f"[Client] Connected!")
            
            # Send JOIN message
            with self.lock:
                join_msg = create_chat_message(TYPE_JOIN, self.user_id, self.vector_clock,
                                                f"{self.user_id} joined the chat.")
            send_tcp_message(self.socket, join_msg)
            
            self.running = True
            return True
            
        except Exception as e:
            print(f"[Client] Connection failed: {e}")
            if self.socket:
                self.socket.close()
                self.socket = None
            return False
    
    def start_chat(self):
        """Start the chat session"""
        # Start receive thread
        recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        recv_thread.start()
        
        # Main input loop
        print(f"\n[Chat] Welcome {self.user_id}! Type your messages below.")
        print("[Chat] Type '/quit' to leave.\n")
        
        try:
            while self.running:
                try:
                    content = input("Your message: ")
                    
                    if content.lower() == '/quit':
                        self._send_leave()
                        break
                    
                    if content.strip():
                        self._send_chat(content)
                        
                except EOFError:
                    break
                    
        except KeyboardInterrupt:
            print("\n[Chat] Interrupted")
        finally:
            self.running = False
            if self.socket:
                self.socket.close()
            print("[Chat] Disconnected")
    
    def _send_chat(self, content):
        """Send a chat message"""
        with self.lock:
            self.vector_clock.increment()
            msg = create_chat_message(TYPE_CHAT, self.user_id, self.vector_clock, content)
        
        try:
            send_tcp_message(self.socket, msg)
        except Exception as e:
            print(f"[Error] Failed to send message: {e}")
            self.running = False
    
    def _send_leave(self):
        """Send leave message"""
        with self.lock:
            msg = create_chat_message(TYPE_LEAVE, self.user_id, self.vector_clock,
                                       f"{self.user_id} left the chat.")
        try:
            send_tcp_message(self.socket, msg)
        except:
            pass
    
    def _receive_loop(self):
        """Receive and process messages from server"""
        try:
            while self.running:
                message = receive_tcp_message(self.socket)
                
                if message is None:
                    safe_print("[Chat] Server closed connection")
                    self.running = False
                    break
                
                self._handle_message(message)
                
        except Exception as e:
            if self.running:
                safe_print(f"[Error] Receive error: {e}")
            self.running = False
    
    def _handle_message(self, message):
        """Handle received message with causal ordering"""
        msg_type = message.get('type')
        sender = message.get('sender')
        received_clock = message.get('vector_clock', {})
        content = message.get('content', '')
        
        messages_to_deliver = []
        
        with self.lock:
            if msg_type == TYPE_JOIN:
                # Add new user to vector clock
                self.vector_clock.add_entry(sender)
                self.vector_clock.merge(received_clock)
                messages_to_deliver.append(message)
                # Check if this unlocks held-back messages
                messages_to_deliver.extend(self._check_holdback_queue())
                
            elif msg_type == TYPE_CHAT:
                # Causal ordering check
                if self.vector_clock.is_deliveravle(received_clock, sender):
                    self.vector_clock.merge(received_clock)
                    messages_to_deliver.append(message)
                    messages_to_deliver.extend(self._check_holdback_queue())
                else:
                    # Hold back for causal ordering
                    self.hold_back_queue.append(message)
                    
            elif msg_type == TYPE_LEAVE:
                messages_to_deliver.append(message)
        
        # Deliver messages (outside lock)
        for msg in messages_to_deliver:
            self._deliver(msg)
    
    def _check_holdback_queue(self):
        """Check and return deliverable messages from hold-back queue"""
        deliverable = []
        
        while True:
            progress = False
            for message in list(self.hold_back_queue):
                sender = message.get('sender')
                received_clock = message.get('vector_clock', {})
                
                if self.vector_clock.is_deliveravle(received_clock, sender):
                    self.vector_clock.merge(received_clock)
                    deliverable.append(message)
                    self.hold_back_queue.remove(message)
                    progress = True
                    break
            
            if not progress:
                break
        
        return deliverable
    
    def _deliver(self, message):
        """Deliver message to user"""
        msg_type = message.get('type')
        sender = message.get('sender')
        content = message.get('content', '')
        
        if sender == self.user_id:
            return  # Don't show own messages
        
        if msg_type == TYPE_JOIN:
            safe_print(f">>> {sender} joined the chat")
        elif msg_type == TYPE_CHAT:
            safe_print(f"{sender}: {content}")
        elif msg_type == TYPE_LEAVE:
            safe_print(f"<<< {sender} left the chat")


def main():
    """Main entry point"""
    print("=" * 60)
    print("       Welcome to the Distributed Chat Client")
    print("=" * 60)
    
    # Get user ID
    user_id = input("\nEnter your username: ").strip()
    if not user_id:
        user_id = f"User_{os.getpid()}"
    
    client = ChatClient(user_id)
    
    while True:
        # Discover chatrooms
        servers = client.discover_chatrooms()
        
        if servers:
            client.display_chatrooms(servers)
        else:
            print("\n[!] No servers found. Make sure a Leader is running.")
        
        # Prompt for connection
        result = client.prompt_connection()
        
        if result is None:
            print("\nGoodbye!")
            break
        elif result == 'refresh':
            continue
        else:
            ip, port = result
            if client.connect(ip, port):
                client.start_chat()
                # After chat ends, ask if want to reconnect
                again = input("\nConnect to another room? (y/n): ").strip().lower()
                if again != 'y':
                    print("\nGoodbye!")
                    break
                # Reset client state for new connection
                client = ChatClient(user_id)


if __name__ == '__main__':
    main()