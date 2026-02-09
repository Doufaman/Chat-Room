"""
Message history management for chat rooms.
Two-phase storage:
  Phase 1: In-memory FIFO queue (temporary storage)
  Phase 2: File-based persistence (when queue is full)
"""
import json
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

MAX_HISTORY_DEFAULT = 10  # Max messages in memory queue

class ChatMessageHistory:
    """
    Two-phase message storage system for chat rooms.
    
    Phase 1: Fixed-size FIFO queue (memory)
      - Fast access for recent messages
      - Limited capacity (default: 100 messages)
    
    Phase 2: File persistence (disk)
      - Triggered when memory queue is full
      - One batch write per trigger (all queued messages)
      - Append-only format (JSONL for easy parsing)
    """
    
    def __init__(self, room_id, room_name, max_history=MAX_HISTORY_DEFAULT, storage_dir="./chat_history"):
        """
        Args:
            room_id: Unique room identifier
            room_name: Display name of the room
            max_history: Maximum messages in memory queue
            storage_dir: Directory to store persistent files
        """
        self.room_id = room_id
        self.room_name = room_name
        self.max_history = max_history
        
        # Phase 1: In-memory FIFO queue
        self.history_queue = deque(maxlen=max_history)  # Auto-remove oldest when full
        
        # File storage path
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Persistent file path: ./chat_history/room_{room_name}.jsonl
        # use room_name as unique identifer for file naming
        self.history_file = self.storage_dir / f"{room_name}.jsonl"
        
        # Thread safety
        self.lock = threading.Lock()
        
        # Statistics
        self.total_messages_saved = 0
        self.last_persist_count = 0
    
    def add_message(self, msg_type, sender, content, vector_clock=None):
        """
        Add a message to the history.
        
        Args:
            msg_type: 'JOIN', 'CHAT', or 'LEAVE'
            sender: User ID of the sender
            content: Message content
            vector_clock: Vector clock dict for causal ordering
        
        Return:
            bool: True if persistence was triggered, False otherwise
        """
        with self.lock:
            # Create message record with metadata
            message_record = {
                'timestamp': datetime.now().isoformat(),
                'type': msg_type,
                'sender': sender,
                'content': content,
                'vector_clock': vector_clock or {}
            }
            
            # Add to memory queue
            self.history_queue.append(message_record)
            
            # Check if persistence is needed
            # Trigger when queue reaches max capacity
            queue_was_full = len(self.history_queue) == self.max_history
            
            # TODO: synchronize history with other servers
            if queue_was_full:
                # Persistence triggered - save all messages in queue
                self._persist_to_file()
                return True
        
        return False
    
    def _persist_to_file(self):
        """
        Write all messages from queue to persistent storage.
        Internal method - called when queue is full.
        
        Format: JSONL (JSON Lines)
          - One message per line
          - Easy to parse and append
          - Human-readable
        """
        try:
            with open(self.history_file, 'a', encoding='utf-8') as f:
                for message in self.history_queue:
                    json_line = json.dumps(message, ensure_ascii=False)
                    f.write(json_line + '\n')
            
            self.last_persist_count = len(self.history_queue)
            self.total_messages_saved += self.last_persist_count
            
            print(f"[MessageHistory Room {self.room_id}] "
                  f"Persisted {self.last_persist_count} messages to {self.history_file}")
            
            # Clear the queue after persisting to avoid duplicate saves
            self.history_queue.clear()
            
        except Exception as e:
            print(f"[MessageHistory Room {self.room_id}] "
                  f"ERROR persisting to file: {e}")
    
    def get_recent_messages(self, count=20):
        """
        Retrieve recent messages from memory queue.
        
        Args:
            count: Number of recent messages to retrieve
        
        Returns:
            list: Message records (most recent last)
        """
        with self.lock:
            recent = list(self.history_queue)[-count:]
            return recent
    
    def get_all_persisted_messages(self):
        """
        Read all persisted messages from file.
        
        Returns:
            list: All message records from file
        """
        messages = []
        
        if not self.history_file.exists():
            return messages
        
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        messages.append(json.loads(line))
        except Exception as e:
            print(f"[MessageHistory Room {self.room_id}] "
                  f"ERROR reading persisted messages: {e}")
        
        return messages
    
    def get_statistics(self):
        """Get storage statistics"""
        return {
            'room_id': self.room_id,
            'room_name': self.room_name,
            'memory_queue_size': len(self.history_queue),
            'max_memory_size': self.max_history,
            'total_persisted_messages': self.total_messages_saved,
            'last_persist_batch_size': self.last_persist_count,
            'storage_file': str(self.history_file),
            'storage_file_exists': self.history_file.exists(),
            'storage_file_size_kb': round(self.history_file.stat().st_size / 1024, 2) 
                                    if self.history_file.exists() else 0
        }
    
    def clear_memory(self):
        """Clear only the in-memory queue (keep persistent data)"""
        with self.lock:
            self.history_queue.clear()
    
    def export_all_messages(self, output_file=None):
        """
        Export all messages (memory + persisted) to a single file.
        
        Args:
            output_file: Optional output file path
        
        Returns:
            dict: Export summary
        """
        output_file = output_file or self.storage_dir / f"export_room_{self.room_id}.json"
        
        with self.lock:
            all_messages = {
                'room_id': self.room_id,
                'room_name': self.room_name,
                'export_time': datetime.now().isoformat(),
                'memory_messages': list(self.history_queue),
                'persisted_messages': self.get_all_persisted_messages()
            }
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(all_messages, f, ensure_ascii=False, indent=2)
            
            total = len(all_messages['memory_messages']) + len(all_messages['persisted_messages'])
            print(f"[MessageHistory Room {self.room_id}] "
                  f"Exported {total} messages to {output_file}")
            
            return {
                'success': True,
                'file': str(output_file),
                'total_messages': total
            }
        
        except Exception as e:
            print(f"[MessageHistory Room {self.room_id}] ERROR exporting: {e}")
            return {'success': False, 'error': str(e)}