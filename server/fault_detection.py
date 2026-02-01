# fault detection module
# 1. heartbeat mechanism: sending, receiving, monitoring and handling abnormalities
# 2. handling the abnormal state report of server from client

import threading
import time
from utills.logger import get_logger
from server.config import HEARTBEAT_INTERVAL, HEARTBEAT_LEADER_TIMEOUT, HEARTBEAT_SERVER_TIMEOUT  
from server.config import SUSPECT, DEAD, ACTIVE

logger = get_logger("fault_detection")

# TODO: Set leader's address in main.py when becoming follower/leader
# TODO: Save socket between server and leader in communication module
# todo: invoke "are you alive" messages from other servers
# todo: invoke "probe response" messages from other servers
# todo: invoke "handle_heartbeat" from main event loop
# todo: 所有和leader的通信带上对leader状态的检查
class Heartbeat:
    def __init__(self, server):
        self.server = server
        self.interval = HEARTBEAT_INTERVAL  
        self.leader_timeout = HEARTBEAT_LEADER_TIMEOUT
        self.server_timeout = HEARTBEAT_SERVER_TIMEOUT

    def start(self):
        """Start sending heartbeats."""
        self.schedule_next_heartbeat()

    def schedule_next_heartbeat(self):
        """Schedule the next heartbeat."""
        self.timer = threading.Timer(self.interval, self.send_heartbeat)
        self.timer.start()

    def send_heartbeat(self):
        """Send a heartbeat message to other servers."""
        heartbeat_msg = {
            "msg_type": "HEARTBEAT",
            "message": {
                "server_id": self.server.server_id,
                "timestamp": time.time(),
                "identity": self.server.identity
            }
        }
        # select different sending methods based on server role
        # todo: determine sending method
        if self.server.identity == "LEADER":
            try:
                self.server.network_manager.send_broadcast(heartbeat_msg)
            except Exception as e:
                logger.error(f"leader heartbeat broadcast failed: {e}")
        else:
            heartbeat_msg["message"]["load_info"] = self.server.get_current_load()
            # If follower -> send only to current leader
            leader_addr = getattr(self.server, "leader_address", None)
            if not leader_addr:
                logger.warning("no leader known, cannot send follower heartbeat")
            else:
                try:
                    pass # sending via network manager: tcp socket
                except Exception as e:
                    logger.error(f"follower heartbeat send to leader {leader_addr} failed: {e}")
        self.schedule_next_heartbeat()

    def handle_heartbeat(self, msg):
        """Handle received heartbeat messages."""
        timestamp = msg["timestamp"]
        sender_identity = msg["identity"]
        # Process heartbeat based on sender and receiver identities
        if sender_identity == "FOLLOWER" and self.server.identity == "LEADER":
            load_info = msg.get("load_info", {})
            server_id = msg["server_id"]
            self.server.membership.update_heartbeat(server_id, timestamp)
            self.server.membership.update_server_load(server_id, load_info)
        elif sender_identity == "LEADER" and self.server.identity == "FOLLOWER":
            self.server.leader_latest_heartbeat = timestamp
        else:
            logger.warning(f"Received heartbeat from unexpected identity {sender_identity} while being {self.server.identity}")
            return

    def start_timeout_checker(self):
        """Start checking for heartbeat timeouts."""
        threading.Thread(target=self.check_timeouts, daemon=True).start()

    def check_timeouts(self):
        """Check for servers that have timed out."""
        while True:
            if self.server.identity == "LEADER":
                time.sleep(self.server_timeout)
                probe_wait = 1  # wait time for probe responses
                # 1. get suspected servers
                suspected_servers = self.get_suspected_servers(self.server_timeout)
                if suspected_servers:
                    logger.info(f"Suspected servers detected: {suspected_servers}. Sending probes.")
                    for server_id in suspected_servers:
                        probe_msg = {
                            "msg_type": "ARE_YOU_ALIVE",
                            "message": {"server_id": self.server.server_id, 
                                        "timestamp": time.time(),
                                        "sender": getattr(self.server, "identity", None)
                                        }
                        }
                        # 2. send probe to suspected server
                        try:
                            pass # todo: sending via network manager: udp socket
                        except Exception as e:
                            logger.debug(f"Failed to send probe to suspected server {server_id} {e}")

                    # 3. wait for probe responses (re-check membership after wait)
                    time.sleep(probe_wait)

                    still_suspected = self.get_suspected_servers(self.server_timeout)
                    for server_id in still_suspected:
                        logger.warning(f"Server {server_id} did not respond to probe, treating as dead.")
                        # 4. mark server as dead
                        self.server.membership.update_server_status(server_id, DEAD)
                        # 5. todo:call higher-level fault discovery (leave implementation to caller)
                        try:
                            pass
                        except Exception as e:
                            logger.debug(f"fault_discovery call failed for {server_id}: {e}")
            else:
                time.sleep(self.leader_timeout)
                # leader timeout detection
                if time.time() - self.server.leader_latest_heartbeat > self.leader_timeout:
                    logger.warning("Leader heartbeat timeout detected.")
                    #  todo: Handle leader timeout (e.g., start election and servers send info to new leader)

    def get_suspected_servers(self, timeout):
        """Return a list of suspected servers."""
        suspected_servers = []
        # get all servers and check their last heartbeat timestamps
        for server_id, last_heartbeat_ts in self.server.membership.get_active_servers().items():
            if time.time() - last_heartbeat_ts > timeout:
                suspected_servers.append(server_id)
                self.server.membership.update_server_status(server_id, SUSPECT)
        return suspected_servers
    
    def handle_probe_request(self, msg):
        """Handle probe requests from leader."""
        timestamp = msg["timestamp"]
        requester_identity = msg["sender"]
        if requester_identity != "LEADER" or self.server.identity != "FOLLOWER":
            logger.warning(f"Received probe request from unexpected identity {requester_identity} while being {self.server.identity}")
            return
        self.server.leader_latest_heartbeat = timestamp

        response_msg = {
            "msg_type": "PROBE_RESPONSE",
            "message": {
                "server_id": self.server.server_id,
                "timestamp": time.time()
            }
        }
        # send probe response back to requester
        try:
            pass # todo: sending via network manager: udp socket
            logger.info(f"Server {self.server.server_id} sent probe response to leader.")
        except Exception as e:
            logger.error(f"Server {self.server.server_id} failed to send probe response to server: {e}")
    
    def handle_probe_response(self, msg):
        """Handle probe responses from servers."""
        server_id = msg["server_id"]
        timestamp = msg["timestamp"]
        self.server.membership.update_heartbeat(server_id, timestamp)
        self.server.membership.update_server_status(server_id, ACTIVE)
        logger.info(f"Received probe response from server {server_id}, marked as ACTIVE.")


class HandleAbnormalStateReport:
    def __init__(self, server):
        self.server = server

    def handle_report(self, report):
        """Handle abnormal state reports from clients."""
        server_id = report["server_id"]
        logger.warning(f"Received abnormal state report for server {server_id}: server {server_id} does not respond.")
        # 1. mark server as suspect
        self.server.membership.update_server_status(server_id, SUSPECT)
        # 2. send probe to the reported server
        probe_msg = {
            "msg_type": "ARE_YOU_ALIVE",
            "message": {"server_id": self.server.server_id, 
                        "timestamp": time.time(),
                        "sender": getattr(self.server, "identity", None)
                        }
        }
        try:
            pass # todo: sending via network manager: udp socket
            logger.info(f"Sent probe to reported server {server_id}.")
        except Exception as e:
            logger.debug(f"Failed to send probe to reported server {server_id} {e}")
        # 3. wait for probe response
        probe_wait = 1  # wait time for probe responses
        time.sleep(probe_wait)
        # 4. re-check server status
        server_status = self.server.membership.get_serrver_status(server_id)
        if server_status == ACTIVE:
            logger.info(f"Server {server_id} responded to probe, marked as ACTIVE.")
        elif server_status == DEAD:
            logger.warning(f"Server {server_id} is already marked as DEAD.")
        else:
            logger.warning(f"Server {server_id} did not respond to probe, treating as DEAD.")
            self.server.membership.update_server_status(server_id, DEAD)
            # 5. todo:call higher-level fault discovery (leave implementation to caller)
            try:
                pass
            except Exception as e:
                logger.debug(f"fault_discovery call failed for {server_id}: {e}")

        