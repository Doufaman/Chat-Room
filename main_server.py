import time
import uuid
import threading

from utills.logger import setup_logger
import logging

from network.network_manager import NetworkManager

from server.roles.server import Server
# from server.roles.leader import Leader
# from server.roles.follower import Follower
from server.dynamic_discovery import dynamic_discovery
from server.election_manager import ElectionManager
from server.chatroom_manager import ChatroomManager
from server.config import TYPE_FOLLOWER, TYPE_LEADER
from utills.ip_validator import prompt_valid_ip

DEBUG = False  # or False

if DEBUG:
    setup_logger(logging.DEBUG)
else:
    setup_logger(logging.INFO)

class StartupEngine:
    def __init__(self,
                 self_ip,
                 #config
                 ):
        # create unique server ID
        self.self_ip = self_ip
        
        #self.server_id = str(uuid.uuid4())
        self.server_id = uuid.uuid4().int % (10**9)  # using 9-digit number to identify server



    def start(self, self_ip):     
        # 1. Start communication
        # self.comm.start()
        
        # 2. Enter discovery
        current_identity, leader_address = dynamic_discovery(ip_local = self_ip) # Use current IP for dynamic discovery

        # Create corresponding network manager
        #network_manager, leader_address = NetworkManager(ip_local=self_ip)
        network_manager = NetworkManager(ip_local=self_ip, server_id=self.server_id)

        # Merged leader and follower server class
        server = Server(self.server_id, network_manager, identity=current_identity, leader_address=leader_address)
        server.start()

    

# modify1: move startup code into main.py
if __name__ == '__main__':
    # MY_IP = input("Please enter server IP address: ")
    MY_IP = prompt_valid_ip()  # For MACOS system test
    print(f"[Server] Starting server with IP: {MY_IP}")

    startup_engine = StartupEngine(MY_IP)
    startup_engine.start(MY_IP)

    # Keep main thread running, allow background listener threads to continue
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Server] Shutting down...")
        # modify: move the start od dynamic_discovery into startupengine
        # if current_server._role_instance:
        #    current_server._role_instance.shutdown()