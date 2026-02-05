import threading
import time
import json
from utills.logger import get_logger

logger = get_logger("heartbeat")

class Heartbeat:
    """
    负责心跳的发送与收到消息的基础分发/回复。
    不包含超时检测/死亡判定逻辑（这些由 fault_detection 模块负责）。
    使用方式：
      hb = Heartbeat(server)
      hb.start()
      # 当网络层收到消息并确认是心跳/探测时，调用 hb.handle_incoming(raw_msg, sender_addr)
    """

    def __init__(self, server, interval=None):
        self.server = server
        self.interval = interval or 5.0  # default heartbeat interval in seconds
        self._timer = None

    def start(self):
        """Start periodic heartbeat sending (non-blocking)."""
        self.schedule_next_heartbeat()

    def stop(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def schedule_next_heartbeat(self):
        self._timer = threading.Timer(self.interval, self.send_heartbeat)
        self._timer.daemon = True
        self._timer.start()

    def send_heartbeat(self):
        """Build and send heartbeat. Leader: broadcast; follower: send to leader."""
        heartbeat_msg = {
            "msg_type": "HEARTBEAT",
            "message": {
                "server_id": getattr(self.server, "server_id", None),
                "timestamp": time.time(),
                "identity": getattr(self.server, "identity", None)
            }
        }

        #  if sender is follower, include load info
        if getattr(self.server, "identity", None) == "FOLLOWER":
            load_info = None
            if hasattr(self.server, "get_current_load"):
                try:
                    load_info = self.server.get_current_load()
                except Exception as e:
                    logger.debug(f"get_current_load error: {e}")
            heartbeat_msg["message"]["load_info"] = load_info

        # send via network manager (use existing long-lived TCP for runtime messages)
        try:
            nm = getattr(self.server, "network_manager", None)
            if not nm:
                raise RuntimeError("no network manager available for heartbeat send")

            if getattr(self.server, "identity", None) == "LEADER":
                # TODO: use unicast
                try:
                    # TODO: confirm communication method
                    pass
                except Exception:
                    logger.warning("failed sending heartbeat to followers")
            else:
                leader_addr = getattr(self.server, "leader_address", None)
                if not leader_addr:
                    logger.warning("no leader known, cannot send follower heartbeat")
                else:
                    # TODO: send heartbeat via TCP long-lived connection to leader
                    # Example: nm.send_unicast(leader_addr, json.dumps(heartbeat_msg))
                    pass
        except Exception as e:
            logger.error(f"heartbeat send error: {e}")

        # schedule next
        self.schedule_next_heartbeat()

    def handle_incoming(self, msg, msg_type, sender_addr=None):
        """
        Called by network layer or role when a message is received.
        raw_msg may be dict or JSON string. This method normalizes and forwards to server
        callbacks that implement detection/handling.
        """

        # dispatch to server-side handlers (fault_detection expected to provide these)
        if msg_type == "HEARTBEAT":
            if hasattr(self.server, "handle_heartbeat"):
                try:
                    self.server.handle_heartbeat(msg, sender_addr=sender_addr)
                except Exception as e:
                    logger.debug(f"server.handle_heartbeat error: {e}")
        elif msg_type in ("ARE_YOU_ALIVE", "PROBE_REQUEST"):
            # reply immediately (use same network manager / connection)
            if hasattr(self.server, "handle_probe_request"):
                try:
                    self.server.handle_probe_request(msg, sender_addr=sender_addr)
                except Exception as e:
                    logger.debug(f"server.handle_probe_request error: {e}")
            # also send a probe response on same connection
            try:
                nm = getattr(self.server, "network_manager", None) 
                if nm and sender_addr:
                    response = {
                        "msg_type": "PROBE_RESPONSE",
                        "message": {
                            "server_id": getattr(self.server, "server_id", None),
                            "timestamp": time.time()
                        }
                    }
                    # TODO: nm.send_unicast(sender_addr, json.dumps(response))  # use TCP conn if available
                    pass
            except Exception as e:
                logger.debug(f"failed sending probe response: {e}")
        elif msg_type in ("PROBE_RESPONSE", "I_AM_ALIVE"):
            if hasattr(self.server, "handle_probe_response"):
                try:
                    self.server.handle_probe_response(msg, sender_addr=sender_addr)
                except Exception as e:
                    logger.debug(f"server.handle_probe_response error: {e}")
        else:
            # ignore here; main.handle_event / role logic may handle other types
            return