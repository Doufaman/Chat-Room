from abc import ABC, abstractmethod

class Role(ABC):
    def __init__(self):
        self._running = True
        # identity: INIT / FOLLOWER / LEADER / CANDIDATE
        self.identity = "INIT"
        # network manager
        self.network_manager = None
        # server id
        self.server_id = None
        # local ip
        self.ip_local = None
        # load info
        self.load_info = None
        
        # Initialize message handler mapping table
        self._msg_map = {
            #"HEARTBEAT": self._handle_heartbeat,
        }

    @abstractmethod
    def start(self):
        """Called once when role becomes active. Should prepare resources but not block indefinitely."""
        pass

    @abstractmethod
    def run(self):
        """Main entry. Could be blocking (loop) or a single operation depending on implementation."""
        pass

        
    @abstractmethod
    def shutdown(self):
        """Cleanly stop the role and release resources. Must be idempotent."""
        pass

        