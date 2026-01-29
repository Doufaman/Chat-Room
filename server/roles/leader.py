import threading
import time

from .base import Role
from server.chatroom_manager import ChatroomManager

class Leader(Role):
    def __init__(self, server_id, network_manager, consensus_manager, chatroom_manager=None):
        super().__init__()
        self.server_id = server_id
        self.network_manager = network_manager
        self.consensus = consensus_manager
        self.chatroom_manager = chatroom_manager  # Use shared instance
        self._identity = "LEADER"
        self.network_manager.set_callback(self.handle_messages)
        self._running = True

    def start(self):
        """Start the leader role"""
        # Start network listening
        self.network_manager.start_listening()
        
        print(f"[Server] Initialized role: {self._identity}, Server ID: {self.server_id}")
        print("[Leader] Setting up leader role...")

    def handle_messages(self, msg_type, message, ip_sender):
        """Handle network messages"""
        if msg_type == "WHO_IS_LEADER":
            print(f'[Leader] receive message from new PC {ip_sender}: {msg_type} {message}')
            self.network_manager.send_broadcast("I_AM_LEADER", 'information')

    def run(self):
        """Main loop for leader"""
        # The consensus manager handles heartbeats, so just keep running
        while self._running:
            time.sleep(1)

    def shutdown(self):
        """Shutdown the leader"""
        self._running = False
        # Don't stop chatroom_manager - it's shared across roles

    

