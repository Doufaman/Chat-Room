
"""nChat Client - Chatroom Client (Pure UDP Communication)
Features:
1. Broadcast to find Leader
2. Get chatroom list from Leader
3. Create/Join/Refresh chatrooms
4. Enter chat mode (TCP) after joining chatroom
"""
import socket
import threading
import sys
import os
import json
import time
from utills.logger import get_logger

logger = get_logger("chat_client")

from network.chatting_messenger import (
    send_tcp_message, receive_tcp_message, create_chat_message,
    TYPE_JOIN, TYPE_CHAT, TYPE_LEAVE, TYPE_UPDATE, safe_print
)
from common.vector_clock import VectorClock

# Broadcast port (consistent with server)
PORT_BROADCAST = 9000
DISCOVERY_TIMEOUT = 3.0


class ChatClient:
    """Pure UDP chatroom client"""

    def __init__(self, username):
        self.username = username
        self.leader_ip = None
        self.leader_id = None
        self.chatrooms = []
        self.running = True

        # Chat state
        self.chat_socket = None
        self.chat_running = False
        self.vector_clock = VectorClock(username)
        self.lock = threading.Lock()

    # ==========================================
    # UDP Communication Tools
    # ==========================================
    def _create_udp_socket(self):
        """Create UDP socket bound to broadcast port"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(('', PORT_BROADCAST))
        return sock

    def _send_and_receive(self, msg_type, message, expected_response, timeout=3.0, retries=3):
        """
        Send UDP broadcast and wait for specific response type

        Args:
            msg_type: Message type to send
            message: Message content dict
            expected_response: Expected response message type
            timeout: Timeout for each retry
            retries: Number of retries

        Returns:
            dict or None: Response data or None
        """
        sock = self._create_udp_socket()
        sock.settimeout(timeout)

        request = json.dumps({
            "msg_type": msg_type,
            "message": message,
            "sender_ip": "client"
        }, ensure_ascii=False).encode('utf-8')

        try:
            for attempt in range(retries):
                sock.sendto(request, ('<broadcast>', PORT_BROADCAST))

                deadline = time.time() + timeout
                while time.time() < deadline:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    sock.settimeout(remaining)
                    try:
                        data, addr = sock.recvfrom(65536)
                        resp = json.loads(data.decode('utf-8'))
                        if resp.get('msg_type') == expected_response:
                            return resp
                        # Received unrelated broadcast message, continue waiting
                    except socket.timeout:
                        break
                    except json.JSONDecodeError:
                        continue

            return None
        finally:
            sock.close()

    # ==========================================
    # Core Features
    # ==========================================
    def find_leader(self):
        """Broadcast to find Leader"""
        print("\nSearching for Leader server...")

        resp = self._send_and_receive(
            "WHO_IS_LEADER",
            {"client_name": self.username},
            "I_AM_LEADER",
            timeout=2.0,
            retries=3
        )

        if resp:
            self.leader_ip = resp['message']['leader_ip']
            self.leader_id = resp['message']['leader_id']
            print(f"✓ Found Leader: {self.leader_ip} (Server ID: {self.leader_id})")
            return True

        print("✗ Leader server not found. Please ensure the server is running.")
        return False

    def get_chatroom_list(self):
        """Get chatroom list from Leader (UDP broadcast)"""
        if not self.leader_ip:
            print("✗ Not connected to Leader")
            return False

        resp = self._send_and_receive(
            "GET_CHATROOM_LIST",
            {},
            "CHATROOM_LIST",
            timeout=3.0,
            retries=2
        )

        if resp:
            self.chatrooms = resp['message'].get('chatrooms', [])
            return True

        print("✗ Retrieving chatroom list timed out")
        return False

    def display_chatrooms(self):
        """Display available chatroom list"""
        if not self.chatrooms:
            print("\nNo chatrooms are currently available.")
            return

        print("\n" + "=" * 70)
        print("Available Chatrooms:")
        print("=" * 70)
        print(f"{'No.':<6} {'Chatroom ID':<15} {'Name':<20} {'Server':<18} {'Online':<10}")
        print("-" * 70)

        for idx, room in enumerate(self.chatrooms, 1):
            port = room.get('port', '?')
            clients = room.get('clients_count', 0)
            print(f"{idx:<6} {room['chatroom_id']:<15} {room['name']:<20} "
                  f"{room['server_ip']}:{port:<6} {clients:<10}")

        print("=" * 70)

    def create_chatroom(self):
        """Create new chatroom (UDP broadcast)"""
        if not self.leader_ip:
            print("✗ Not connected to Leader")
            return False

        room_name = input("\nEnter new chatroom name: ").strip()
        if not room_name:
            print("✗ Chatroom name cannot be empty")
            return False

        print(f"Creating chatroom '{room_name}'...")

        resp = self._send_and_receive(
            "CREATE_CHATROOM",
            {"name": room_name},
            "CHATROOM_CREATED",
            timeout=10.0,
            retries=1
        )

        if resp:
            room_info = resp['message']['chatroom_info']
            print(f"\n✓ Chatroom created successfully!")
            print(f"  Chatroom ID: {room_info['chatroom_id']}")
            print(f"  Name: {room_info['name']}")
            print(f"  Server: {room_info['server_ip']}:{room_info['port']}")
            return True

        print("✗ Create chatroom timed out")
        return False

    def join_chatroom(self):
        """Select and join chatroom"""
        if not self.chatrooms:
            print("\nNo available chatrooms, please create one first")
            return

        self.display_chatrooms()

        try:
            choice = input("\nEnter chatroom number to join (or enter IP:PORT directly): ").strip()

            if ':' in choice:
                parts = choice.split(':')
                if len(parts) == 2:
                    server_ip = parts[0]
                    port = int(parts[1])
                else:
                    print("✗ Format error, please use IP:PORT format")
                    return
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(self.chatrooms):
                    room = self.chatrooms[idx]
                    server_ip = room['server_ip']
                    port = room['port']
                else:
                    print("✗ Invalid number")
                    return

            # Connect to chatroom (TCP long connection for actual chat)
            self._connect_and_chat(server_ip, port)

        except ValueError:
            print("✗ Input format error")
        except Exception as e:
            print(f"✗ Failed to join chatroom: {e}")

    # ==========================================
    # Chat Features (TCP connection to specific chatroom)
    # ==========================================
    def _connect_and_chat(self, server_ip, port):
        """Connect to chatroom and start chatting"""
        print(f"\nConnecting to chatroom {server_ip}:{port}...")

        try:
            self.chat_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.chat_socket.settimeout(10.0)
            self.chat_socket.connect((server_ip, port))
            self.chat_socket.settimeout(None)
            safe_print(f"✓ Connected!")

            # Send JOIN message
            with self.lock:
                join_msg = create_chat_message(
                    TYPE_JOIN, self.username, self.vector_clock,
                    f"{self.username} joined the chat."
                )
            send_tcp_message(self.chat_socket, join_msg)

            self.chat_running = True

            # Start receive thread
            recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
            recv_thread.start()

            safe_print(f"\n[Chat] Welcome {self.username}! Type messages to start chatting.")
            safe_print("[Chat] Type /quit to leave the chatroom.\n")

            # Message sending loop
            while self.chat_running:
                try:
                    content = input("Your message: ")
                    if content.lower() == '/quit':
                        self._send_leave()
                        break
                    if content.strip():
                        self._send_chat(content)
                except EOFError:
                    break

        except Exception as e:
            safe_print(f"✗ Connection failed: {e}")
        finally:
            self.chat_running = False
            if self.chat_socket:
                self.chat_socket.close()
                self.chat_socket = None
            safe_print("[Chat] Disconnected")

    def _send_chat(self, content):
        """Send chat message"""
        with self.lock:
            self.vector_clock.increment()
            msg = create_chat_message(TYPE_CHAT, self.username, self.vector_clock, content)
        try:
            send_tcp_message(self.chat_socket, msg)
        except Exception as e:
            safe_print(f"[Error] Send failed: {e}")
            self.chat_running = False

    def _send_leave(self):
        """Send leave message"""
        with self.lock:
            msg = create_chat_message(
                TYPE_LEAVE, self.username, self.vector_clock,
                f"{self.username} left the chat."
            )
        try:
            send_tcp_message(self.chat_socket, msg)
        except:
            pass

    def _receive_loop(self):
        """Receive chat messages"""
        hold_back_queue = []
        try:
            while self.chat_running:
                message = receive_tcp_message(self.chat_socket)
                if message is None:
                    safe_print("[Chat] Server disconnected")
                    self.chat_running = False
                    break

                msg_type = message.get('type')
                sender = message.get('sender')
                received_clock = message.get('vector_clock', {})
                content = message.get('content', '')

                with self.lock:
                    if msg_type == TYPE_UPDATE:
                        # Server sent us the full member list (vector clock)
                        self.vector_clock.merge(received_clock)
                        safe_print(f"[Chat] Member list updated")
                        continue
                    
                    if msg_type == TYPE_JOIN:
                        self.vector_clock.add_entry(sender)
                        self.vector_clock.merge(received_clock)
                        safe_print(f">>> {sender} joined the chatroom (Debug: VC={received_clock})")
                    elif msg_type == TYPE_CHAT:
                        if self.vector_clock.is_deliveravle(received_clock, sender):
                            self.vector_clock.merge(received_clock)
                            safe_print(f"{sender}: {content} (Debug: VC={received_clock})")
                        else:
                            hold_back_queue.append(message)
                    elif msg_type == TYPE_LEAVE:
                        safe_print(f"<<< {sender} left the chatroom (Debug: VC={received_clock})")

                # Check hold-back queue
                with self.lock:
                    changed = True
                    while changed:
                        changed = False
                        for msg in list(hold_back_queue):
                            s = msg.get('sender')
                            rc = msg.get('vector_clock', {})
                            if self.vector_clock.is_deliveravle(rc, s):
                                self.vector_clock.merge(rc)
                                safe_print(f"{s}: {msg.get('content', '')} (Debug: VC={rc} [from hold-back])")
                                hold_back_queue.remove(msg)
                                changed = True
                                break

        except Exception as e:
            if self.chat_running:
                safe_print(f"[Error] Receive error: {e}")
            self.chat_running = False

    # ==========================================
    # Menu
    # ==========================================
    def show_menu(self):
        """Display main menu"""
        print("\n" + "=" * 60)
        print("Chatroom Client - Main Menu")
        print("=" * 60)
        print("(1) Create Chatroom")
        print("(2) Join Chatroom")
        print("(3) Refresh Chatroom List")
        print("(4) Re-find Leader")
        print("(5) Exit")
        print("=" * 60)

    def run(self):
        """Run client"""
        print("=" * 60)
        print("       Welcome to Distributed Chatroom Client")
        print("=" * 60)
        print(f"\nWelcome, {self.username}!")

        # Find Leader
        if not self.find_leader():
            print("\nCannot find Leader server, program exiting")
            return

        # Main loop
        while self.running:
            # Auto-refresh chatroom list
            if self.get_chatroom_list():
                self.display_chatrooms()

            self.show_menu()
            choice = input("\nPlease select operation (1-5): ").strip()

            if choice == '1':
                self.create_chatroom()
            elif choice == '2':
                self.join_chatroom()
            elif choice == '3':
                print("\nRefreshing chatroom list...")
                if self.get_chatroom_list():
                    self.display_chatrooms()
                    print("✓ List refreshed")
                else:
                    print("✗ Refresh failed")
            elif choice == '4':
                self.find_leader()
            elif choice == '5':
                print(f"\nGoodbye, {self.username}!")
                self.running = False
            else:
                print("\n✗ Invalid selection, please enter 1-5")

        print("\nClient exited")


def main():
    """Main function"""
    print("=" * 60)
    print("       Distributed Chatroom Client")
    print("=" * 60)

    username = input("\nPlease enter your username: ").strip()
    if not username:
        username = f"User_{os.getpid()}"

    client = ChatClient(username)
    try:
        client.run()
    except KeyboardInterrupt:
        print(f"\n\nGoodbye, {username}!")
    except Exception as e:
        print(f"\nProgram error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
