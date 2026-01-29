import socket
import threading
import time

from .base import Role
from server.chatroom_manager import ChatroomManager

class Follower(Role):
    def __init__(self, server_id, network_manager, consensus_manager, leader_address, chatroom_manager=None):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager
        self.consensus = consensus_manager
        self._identity = "FOLLOWER"
        self._running = True
        self.leader_address = leader_address
        self.chatroom_manager = chatroom_manager  # Use shared instance

    def start(self):
        """Start the follower role"""
        # Start network listening
        self.network_manager.start_listening()
        print(f"[Server] Initialized role: {self._identity}, Server ID: {self.server_id}")
        print(f"[Follower] Connected to Leader at {self.leader_address}")

    def run(self):
        """Main loop for follower"""
        # Consensus manager handles connection to leader
        while self._running:
            time.sleep(1)

    def shutdown(self):
        """Shutdown the follower"""
        self._running = False
        # Don't stop chatroom_manager - it's shared across roles


