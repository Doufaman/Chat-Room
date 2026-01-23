from abc import ABC, abstractmethod

class Role(ABC):
    def __init__(self):
        self._running = True
        
        # 初始化消息处理器映射表
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

        '''
    @abstractmethod
    def shutdown(self):
        """Cleanly stop the role and release resources. Must be idempotent."""
        pass
        '''