"""
Message history management for chat rooms.
Two-phase storage:
  Phase 1: In-memory FIFO queue (temporary storage)
  Phase 2: File-based persistence (when queue is full)
"""
import json
import threading
import socket
from collections import deque
from datetime import datetime
from pathlib import Path

from network.network_manager import create_udp_socket, send_udp_message, receive_udp_message, PORT_BACKUP

from utills.logger import get_logger
logger = get_logger("backup")

MAX_HISTORY_DEFAULT = 5  # Max messages in memory queue
DEFAULT_STORAGE_DIR = Path(__file__).parent.parent / "chat_history"#"./chat_history"
TYPE_BACKUP = "BACKUP"  # Message type for backup coordination (not implemented yet)

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
    
    def __init__(self, room_id, room_name, 
                 network_manager,
                 server,
                 max_history=MAX_HISTORY_DEFAULT, storage_dir=DEFAULT_STORAGE_DIR):
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
        self.network_manager = network_manager
        self.server = server

        # Get current group members from server's membership
        #current_group = self.server.membership.get_group_servers()
        
        # Phase 1: In-memory FIFO queue
        self.history_queue = deque(maxlen=max_history)  # Auto-remove oldest when full
        
        # File storage path
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Persistent file path: storage_dir/room_{room_name}.jsonl
        # use room_name as unique identifer for file naming
        self.history_file = self.storage_dir / f"{room_name}.jsonl"
        
        # Thread safety
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        
        # Statistics
        self.total_messages_saved = 0
        self.last_persist_count = 0

        # Create independent UDP socket for backup messages
        self.udp_socket = create_udp_socket('0.0.0.0', PORT_BACKUP)
        # Enable Broadcast
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.local_ip = network_manager.ip_local
        
        # Store server_id for filtering own messages
        self.my_id = server.server_id
        
        logger.info(f"[MessageHistory] Initialized for Room '{room_name}' (ID: {room_id})")
        logger.info(f"[MessageHistory] UDP socket listening on port {PORT_BACKUP}")
        logger.info(f"[MessageHistory] Server ID: {self.my_id}, Local IP: {self.local_ip}")

    def start(self):
        """Start UDP listener thread for receiving backup messages"""
        listener_thread = threading.Thread(target=self._udp_listener, daemon=True, name=f"MsgHistory-UDP-{self.room_name}")
        listener_thread.start()
        logger.info(f"[MessageHistory Room {self.room_id}] UDP listener thread started")
        print(f"[MessageHistory] Started UDP listener for room '{self.room_name}' on port {PORT_BACKUP}")

    def _udp_listener(self):
        """Listen for message history replication messages from other servers"""
        logger.info(f"[Room {self.room_name}] UDP listener running on port {PORT_BACKUP}")
        print(f"[MessageHistory] UDP listener is now active for room '{self.room_name}'")
        
        while not self.stop_event.is_set():
            try:
                message, addr = receive_udp_message(self.udp_socket)
                if not message:
                    continue
                print(f"[MessageHistory] Received UDP message history from {addr}")
                # 检查消息是否是列表（备份消息）
                
                # 处理结构化消息
                msg_type = message.get('msg_type')
                msg_body = message.get('message', {})
                sender_ip = message.get('sender_ip', addr[0])
                room_name = message.get('room_name', '')  # 获取房间名称
                room_id = message.get('room_id', '')
                server_id = message.get('server_id', '')  # ← 获取负责该聊天室的服务器ID
                
                logger.info(f"Received {msg_type} from {sender_ip} for room '{room_name}' (server {server_id})")
                print(f"[MessageHistory] Type: {msg_type}, Room: '{room_name}', Server: {server_id}, Sender: {sender_ip}")
                
                # Forward to message handler with room info
                self.handle_messages_history(msg_type, msg_body, sender_ip, room_name, room_id, server_id)
                
            except Exception as e:
                logger.error(f"Error in UDP listener: {e}")
                print(f"[MessageHistory] ✗ UDP listener error: {e}")
                import traceback
                traceback.print_exc()

    def handle_messages_history(self, msg_type, message, sender_ip, room_name='', room_id='', server_id=''):
        """Handle received backup coordination messages"""
        if msg_type == TYPE_BACKUP:
            logger.info(f"Handling BACKUP: {len(message) if isinstance(message, list) else '?'} messages from {sender_ip}")
            print(f"[MessageHistory] Processing BACKUP for room '{room_name}' (server {server_id})")
            
            # Save backup message to the correct room's file
            if isinstance(message, list):
                print(f"[MessageHistory] Saving {len(message)} messages for room '{room_name}' (server {server_id})...")
                self._persist_to_file_otherservers(message, room_name, server_id)
                print(f"[MessageHistory] ✓ Backup saved to '{room_name}_{server_id}.jsonl'")
            else:
                print(f"[MessageHistory] ⚠ Unexpected message format: {type(message)}")
                self._persist_to_file_otherservers([message], room_name, server_id)
        else:
            logger.warning(f"Unknown message type: {msg_type} from {sender_ip}")

    
    def add_message(self, msg_type, sender, content, vector_clock=None):
        """
        Add a message to the history
        
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
            print("the queue was full?", queue_was_full, "current size:", len(self.history_queue))
            
            # TODO: synchronize history with other servers
            if queue_was_full:
                print("FIFO queue reached max capacity. Start backup...")
                
                # IMPORTANT: 在清空队列前先复制消息
                messages_to_backup = list(self.history_queue)
                
                # Send to other servers for backup
                group_members = self.server.membership_manager.group_members
                print(f"Current group ID: {self.server.membership_manager.group_id}")
                print(f"Group members (current group): {group_members}")
                print(f"Local IP: {self.local_ip}")
                
                if not group_members:
                    logger.warning("No group members found! Skipping backup to other servers.")
                    print("[MessageHistory] ⚠ WARNING: No group members, only saving locally")
                
                backup_count = 0
                for target_id, target_ip in group_members.items():
                    if target_ip != self.local_ip:  # Don't send to self
                        logger.info(f"Sending backup to server {target_id} at {target_ip}")
                        # 包含房间信息和服务器ID，以便接收方写入正确的文件
                        message_history_packet = {
                            "msg_type": TYPE_BACKUP,
                            "message": messages_to_backup,
                            "sender_ip": self.local_ip,
                            "room_name": self.room_name,  # 房间名称
                            "room_id": self.room_id,
                            "server_id": self.server.server_id  # ← 负责聊天室的服务器ID
                        }
                        send_udp_message(self.udp_socket, message_history_packet, target_ip, PORT_BACKUP)
                        print(f"→ Sent backup for room '{self.room_name}' (server {self.server.server_id}) to server {target_id} ({target_ip})")
                        backup_count += 1
                
                if backup_count > 0:
                    print(f"[MessageHistory] ✓ Backup sent to {backup_count} server(s)")
                elif group_members:
                    print(f"[MessageHistory] ℹ Only self in group, no backup needed")
                
                # Persistence triggered - save all messages in queue
                self._persist_to_file()
                return True
        
        return False
    
    # write message history to file for other servers to backup
    def _persist_to_file_otherservers(self, message_history, room_name, server_id):
        """
        Save backup messages to the correct room's history file.
        
        Args:
            message_history: List of message records to save
            room_name: Name of the room (used to construct file path)
            server_id: ID of the server responsible for this chatroom
        """
        try:
            # 根据房间名称和服务器ID构建正确的文件路径
            #target_file = self.storage_dir / f"{room_name}_{server_id}.jsonl"
            target_file = self.storage_dir / f"{server_id}_{room_name}.jsonl"
            
            with open(target_file, 'a', encoding='utf-8') as f:
                for message in message_history:
                    json_line = json.dumps(message, ensure_ascii=False)
                    f.write(json_line + '\n')
            
            logger.info(f"Persisted {len(message_history)} backup messages to {target_file}")
            print(f"[MessageHistory] Persisted {len(message_history)} messages to {target_file}")
            
        except Exception as e:
            logger.error(f"ERROR persisting backup to file: {e}")
            print(f"[MessageHistory] ✗ ERROR persisting backup: {e}")
            import traceback
            traceback.print_exc()

    # write local message history to file
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
    
    def get_recent_messages(self, count=5):
        #count: Number of recent messages to retrieve
        message = deque(maxlen=count)
        if not self.history_file.exists():
            return message
        
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        message.append(json.loads(line))
        except Exception as e:
            print(f"[MessageHistory Room {self.room_id}] "
                  f"ERROR reading persisted messages: {e}")
        
        return message
    
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