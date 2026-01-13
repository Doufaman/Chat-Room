import socket
import threading
import time

IS_LEADER = False
LEADER_ADDRESS = ('127.0.0.1', 10001)
known_servers = set()

# Create a UDP socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #use IPv4, UDP

# Buffer size
buffer_size = 1024

# bind local server
server_address = '127.0.0.1'
server_port = int(input("Enter port number to bind the server: "))
server_socket.bind((server_address, server_port))

print(f"Server up and running at {server_address}:{server_port}, Leader: {IS_LEADER}")

known_servers.add((server_address, server_port)) # add self to known_servers

# register to leader server
def register_to_leader():
    if IS_LEADER:
        return
    message = f"REGISTER | {server_address} | {server_port}"
    server_socket.sendto(message.encode(),LEADER_ADDRESS)
    print(f"Sent registration to leader at {LEADER_ADDRESS}")


def handle_registration(data_parts,sender_address):
    address = (data_parts[1], int(data_parts[2]))
    known_servers.add(address)
    print(f"New server registered:{address}")
    print(f"Known servers now:{known_servers}")
    # send updated server list to all known servers
    server_list = "SERVERLIST|" + ";".join([f"{a[0]},{a[1]}" for a in known_servers])
    server_socket.sendto(server_list.encode(), sender_address)
    print(f"Sent server list to {sender_address}")


def receive_server_list(data_parts):
    server_info = data_parts[1].split(";")
    for s in server_info:
        ip, port = s.split(",")
        known_servers.add((ip, int(port)))
    print(f"Updated local server list:{known_servers}")


if not IS_LEADER:
    register_to_leader()


message = 'Hi client! Nice to connect with you!'


'''
while True:
    print('\nWaiting to receive message...\n')

    data, address = server_socket.recvfrom(buffer_size)
    print('Received message from client: ', address)
    print('Message: ', data.decode())

    if data:
        server_socket.sendto(str.encode(message), address)
        print('Replied to client: ', message)
'''

while True:
    print("\nWaiting to receive message...\n")
    data, address = server_socket.recvfrom(buffer_size)
    message = data.decode()
    print(f"Received message from {address}: {message}")

    parts = message.split(" | ")
    message_type = parts[0]

    if message_type == "REGISTER" and IS_LEADER:
        handle_registration(parts, address)
    elif message_type == "SERVERLIST" and not IS_LEADER:
        receive_server_list(parts)
    else:
        print("Received unknown message type.")