import threading
import time

from utills.logger import get_logger

logger = get_logger(__name__)

class Heartbeat:
    def __init__(self, server, interval=5.0):
        self.server = server
        self.interval = interval
        self._thread = None

        self.nm = getattr(server, "network_manager", None)
        if self.nm:
            self.nm.set_callback(self.handle_incoming)

    def start(self):
        """start the heartbeat sending loop in a separate thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _run_loop(self):
        # record next scheduled time
        next_time = time.time()
        while self.running:
            # execute heartbeat send
            self.send_heartbeat()
            
            # calculate how long to sleep until next scheduled time
            next_time += self.interval
            sleep_time = next_time - time.time()
            
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # If the task took too long and missed the next scheduled time,
                # immediately sync to current time to prevent "catch-up" bursts
                next_time = time.time()

    def send_heartbeat(self):
        """Build and send heartbeat. Leader: broadcast; follower: send to leader."""
        # 1. create heartbeat message content (common fields)
        msg_content = {
            "server_id": getattr(self.server, "server_id", None),
            "timestamp": time.time(),
            "identity": getattr(self.server, "identity", None)
        }

        # 2. If Follower, attach load info
        identity = getattr(self.server, "identity", None)
        if identity == "FOLLOWER":
            if hasattr(self.server, "get_current_load"):
                try:
                    msg_content["load_info"] = self.server.get_current_load()
                except Exception as e:
                    logger.debug(f"get_current_load error: {e}")

        # 3. Send via NetworkManager
        try:
            nm = getattr(self.server, "network_manager", None)
            if not nm:
                raise RuntimeError("no network manager available for heartbeat send")

            if identity == "LEADER":
                # Leader: use your batch send function to send to all long-lived connected Followers
                try:
                    nm.send_tcp_msg_to_all_followers("HEARTBEAT", msg_content)
                except Exception as e:
                    logger.warning(f"failed sending heartbeat to followers: {e}")
            else:
                # Follower: send to specified Leader
                leader_id = getattr(self.server, "leader_id", None) # Note: using leader_id is recommended over addr
                if leader_id is None:
                    logger.warning("no leader_id known, cannot send follower heartbeat via TCP")
                else:
                    try:
                        # use TCP long-lived connection if exists
                        nm.send_tcp_message(leader_id, "HEARTBEAT", msg_content)
                    except Exception as e:
                        logger.error(f"Failed to send heartbeat to leader {leader_id}: {e}")
                        
        except Exception as e:
            logger.error(f"heartbeat send error: {e}")



    def handle_incoming(self, msg, msg_type, sender_addr=None):
        """
        Called by network layer or role when a message is received.
        raw_msg may be dict or JSON string. This method normalizes and forwards to server
        callbacks that implement detection/handling.
        """
        logger.debug(f"Heartbeat received message: {msg_type} {msg} from {sender_addr}")

        # dispatch to server-side handlers (fault_detection expected to provide these)
        if msg_type == "HEARTBEAT":
            if hasattr(self.server, "handle_heartbeat"):
                try:
                    self.server.heartbeat_monitor.handle_heartbeat(msg, sender_addr=sender_addr)
                except Exception as e:
                    logger.debug(f"server.handle_heartbeat error: {e}")
        elif msg_type == "ARE_YOU_ALIVE":
            # reply immediately (use same network manager / connection)
            if hasattr(self.server, "handle_probe_request"):
                try:
                    self.server.heartbeat_monitor.handle_probe_request(msg, sender_addr=sender_addr)
                except Exception as e:
                    logger.debug(f"server.handle_probe_request error: {e}")
            # also send a probe response on same connection
            try:
                if self.nm and sender_addr:
                    response = {
                        "server_id": getattr(self.server, "server_id", None),
                        "timestamp": time.time()
                    }
                    self.nm.send_tcp_message(sender_addr, "I_AM_ALIVE", response)
                    pass
            except Exception as e:
                logger.debug(f"failed sending probe response: {e}")
        elif msg_type  == "I_AM_ALIVE":
            if hasattr(self.server, "handle_probe_response"):
                try:
                    self.server.heartbeat_monitor.handle_probe_response(msg, sender_addr=sender_addr)
                except Exception as e:
                    logger.debug(f"server.handle_probe_response error: {e}")
        else:
            # ignore here; main.handle_event / role logic may handle other types
            return