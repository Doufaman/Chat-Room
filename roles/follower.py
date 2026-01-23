import socket
import threading
import time

from .base import Role

class Follower(Role):
    def __init__(self, network, leader_address):
        self.network = network
        self.leader_address = leader_address
        self.known_servers = set()
        self._running = True
        self.buffer_size = 1024

    def start(self):
        print(f"[Follower] Server started, Leader = {self.leader_address}")
        # follower 启动后自动向 leader 注册
        self.register_to_leader()

    def run(self):
        # 主循环：接收消息
        self.listen_loop()

    def register_to_leader(self):
        """Register this server to the leader."""
        msg = f"REGISTER | {self.network.host} | {self.network.tcp_server_port}"
        self.network.send_udp(self.leader_address, msg)
        print(f"[Follower] Registered to leader at {self.leader_address}")

    def receive_server_list(self, data_parts):
        """Receive and update server list from leader."""
        server_info = data_parts[1].split(";")
        for s in server_info:
            ip, port = s.split(",")
            self.known_servers.add((ip, int(port)))
        print(f"[Follower] Updated local server list: {self.known_servers}")

    def listen_loop(self):
        """Main loop to listen for messages."""
        while self._running:
            print("\n[Follower] Waiting to receive message...\n")
            try:
                data, address = self.network.udp_broadcast_receive.recvfrom(self.buffer_size)
                message = data.decode()
                print(f"[Follower] Received message from {address}: {message}")

                parts = message.split(" | ")
                message_type = parts[0]

                if message_type == "SERVERLIST":
                    self.receive_server_list(parts)
                else:
                    print("[Follower] Received unknown message type.")
            except Exception as e:
                print(f"[Follower] Error in listen loop: {e}")
                break

    def shutdown(self):
        """Shutdown follower cleanly."""
        print("[Follower] Shutting down...")
        self._running = False