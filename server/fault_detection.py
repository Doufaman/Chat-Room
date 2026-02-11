# fault detection module
# 1. heartbeat mechanism: sending, receiving, monitoring and handling abnormalities
# 2. handling the abnormal state report of server from client

import threading
import time
from utills.logger import get_logger
from server.config import HEARTBEAT_INTERVAL, HEARTBEAT_LEADER_TIMEOUT, HEARTBEAT_SERVER_TIMEOUT  
from server.config import SUSPECT, DEAD, ACTIVE

from server.heartbeat import Heartbeat  # new module for sending/receiving hearts

logger = get_logger("fault_detection")

class HeartbeatMonitor:
    """
    Keep timeout / probe / dead-detection logic here.
    This class expects:
      - self.server.membership_manager API: get_servers_via_status(), update_heartbeat(...), update_server_status(...)
      - self.server.network_manager (or network) to send probes (we mark sends as TODO)
      - heartbeat.Heartbeat handles periodic sending and basic incoming dispatch
    """
    def __init__(self, server):
        self.server = server 
        self.interval = HEARTBEAT_INTERVAL   
        self.leader_timeout = HEARTBEAT_LEADER_TIMEOUT
        self.server_timeout = HEARTBEAT_SERVER_TIMEOUT


    # ---- methods called by heartbeat.handle_incoming / network layer ----
    def handle_heartbeat(self, msg, sender_addr=None):
        """Called when a HEARTBEAT message arrives (msg is dict)."""
        timestamp = msg.get("timestamp")
        sender_identity = msg.get("identity")
        server_id = msg.get("server_id")

        if sender_identity == "FOLLOWER" and getattr(self.server, "identity", None) == "LEADER":
            load_info = msg.get("load_info", {})
            # update membership_manager heartbeat timestamp and load
            try:
                self.server.membership_manager.update_heartbeat(server_id, timestamp)
                self.server.membership_manager.update_server_load(server_id, load_info)
            except Exception as e:
                logger.debug(f"membership_manager update error for heartbeat from {server_id}: {e}")

        elif sender_identity == "LEADER" and getattr(self.server, "identity", None) == "FOLLOWER":
            # update local leader last heartbeat time (detection uses this)
            self.server.leader_latest_heartbeat = timestamp
        else:
            logger.warning(f"Received heartbeat from unexpected identity {sender_identity} while being {getattr(self.server, 'identity', None)}")
            return

    def handle_probe_request(self, msg, sender_addr=None):
        """Called when a leader probe arrives (ARE_YOU_ALIVE). Reply handled by heartbeat module, update timestamp."""
        timestamp = msg.get("timestamp")
        requester = msg.get("server_id")
        # Only followers should respond to leader probes
        if getattr(self.server, "identity", None) != "FOLLOWER":
            logger.warning("received probe request but not follower; ignoring")
            return
        # update local state that we saw leader probe
        self.server.leader_latest_heartbeat = time.time()
        # actual probe response send is done by heartbeat.handle_incoming (it will call network),
        # but we also expose state updates here.

    def handle_probe_response(self, msg, sender_addr=None):
        """Called when a server replies to our probe."""
        server_id = msg.get("server_id")
        timestamp = msg.get("timestamp")
        try:
            self.server.membership_manager.update_heartbeat(server_id, timestamp)
            self.server.membership_manager.update_server_status(server_id, ACTIVE)
            logger.info(f"Received probe response from server {server_id}, marked ACTIVE.")
        except Exception as e:
            logger.debug(f"probe response handling error: {e}")

    # ---- detection / timeout loop (kept in fault_detection) ----
    def start_timeout_checker(self):
        threading.Thread(target=self.check_timeouts, daemon=True).start()

    def check_timeouts(self):
        """
        Detection loop:
         - leader: find suspected servers, send probes (via network_manager), wait, re-check, mark DEAD and call fault discovery
         - follower: check leader_last_ts and probe leader once, then trigger election if still stale
        """
        poll_interval = max(1, self.interval / 2.0)  # Reduced minimum from 1.0 to 0.5
        probe_wait = 1  # Reduced from 1.0 to 0.5 for faster detection

        while True:
            try:
                if getattr(self.server, "identity", None) == "LEADER":
                    suspected = self.get_suspected_servers(self.server_timeout)
                    if suspected:
                        logger.info(f"Suspected servers: {suspected}. Sending probes.")
                    for sid in suspected:
                        probe_msg = {
                            "server_id": getattr(self.server, "server_id", None), 
                            "timestamp": time.time()
                        }
                        self.server.network_manager.send_tcp_message(sid, "ARE_YOU_ALIVE", probe_msg)
                    time.sleep(probe_wait)
                    still = self.server.membership_manager.get_servers_via_status(SUSPECT)
                    for sid in still:
                        logger.warning(f"{sid} did not respond -> mark DEAD")
                        self.server.membership_manager.update_server_status(sid, DEAD)
                        self.server.membership_manager.remove_server(sid)  # remove from membership
                        self.server.network_manager.unregister_connection(server_id = sid)  # close TCP connection if exists
                        # TODO: call higher-level fault discovery
                        try:
                            if hasattr(self.server, "fault_discovery"):
                                self.server.fault_discovery.handle_dead_server(sid)
                        except Exception as e:
                            logger.debug(f"fault_discovery failed for {sid}: {e}")
                else:
                    # follower: check leader freshness
                    # Skip timeout detection if election is in progress
                    em = getattr(self.server, "election_manager", None)
                    if em and hasattr(em, 'election_in_progress') and em.election_in_progress:
                        logger.debug("Election in progress, skipping heartbeat timeout check")
                        time.sleep(poll_interval)
                        continue
                    
                    leader_ts = getattr(self.server, "leader_latest_heartbeat", None)
                    if leader_ts and (time.time() - leader_ts > self.leader_timeout):
                        logger.warning(f"leader heartbeat timeout detected ({time.time() - leader_ts:.1f}s > {self.leader_timeout}s), start election")
                        # Only trigger if we haven't recently done so
                        if em:
                            # Check if election is already in progress
                            if hasattr(em, 'state') and em.state == 'ELECTION':
                                logger.info("Election already in progress, skipping trigger")
                            else:
                                self.server.network_manager.unregister_connection(server_id = getattr(self.server, "leader_id", None))
                                em.trigger_election("leader heartbeat timeout")
                        else:
                            logger.warning("No election_manager attached to server; cannot trigger election")
                time.sleep(poll_interval)
            except Exception as e:
                logger.exception(f"Exception in check_timeouts loop: {e}")
                time.sleep(poll_interval)

    def get_suspected_servers(self, timeout):
        suspected = []
        try:
            active = self.server.membership_manager.get_servers_via_status(ACTIVE)
            for sid, last in active.items():
                if sid == getattr(self.server, "server_id", None):
                    continue
                if time.time() - last > timeout:
                    suspected.append(sid)
                    self.server.membership_manager.update_server_status(sid, SUSPECT)
        except Exception as e:
            logger.debug(f"get_suspected_servers error: {e}")
        return suspected


class HandleAbnormalStateReport:
    def __init__(self, server):
        self.server = server

    def handle_report(self, failed_ip, failed_port, failed_server_id=None):
        """Handle abnormal state reports from clients."""
        # 1. mark server as suspect
        self.server.membership_manager.update_server_status(failed_server_id, SUSPECT)
        # 2. send probe to the reported server
        probe_msg = {
            "server_id": getattr(self.server, "server_id", None), 
            "timestamp": time.time()
        }
        self.server.network_manager.send_tcp_message(failed_server_id, "ARE_YOU_ALIVE", probe_msg)

        try:
            self.server.network_manager.send_tcp_message(failed_server_id, "ARE_YOU_ALIVE", probe_msg)
            logger.info(f"Sent probe to reported server {failed_server_id}.")
        except Exception as e:
            logger.debug(f"Failed to send probe to reported server {failed_server_id} {e}")
        # 3. wait for probe response
        probe_wait = 1  # wait time for probe responses
        time.sleep(probe_wait)
        # 4. re-check server status
        server_status = self.server.membership_manager.get_serrver_status(failed_server_id)
        if server_status == ACTIVE:
            logger.info(f"Server {failed_server_id} responded to probe, marked as ACTIVE.")
            return
        elif server_status == DEAD:
            logger.warning(f"Server {failed_server_id} is already marked as DEAD.")
        elif server_status == SUSPECT:
            logger.warning(f"Server {failed_server_id} did not respond to probe, treating as DEAD.")
            self.server.membership_manager.update_server_status(failed_server_id, DEAD)
        # 5. todo:call higher-level fault discovery (leave implementation to caller)
        try:
            if hasattr(self.server, "fault_discovery"):
                self.server.fault_discovery.handle_dead_server(failed_server_id)
        except Exception as e:
            logger.debug(f"fault_discovery call failed for {failed_server_id}: {e}")

