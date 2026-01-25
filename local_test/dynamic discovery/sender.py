import socket 

sender_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sender_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
sender_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
broadcast_address = '<broadcast>'
broadcast_port = 6000

message = 'hello, are there any receivers out there?'
sender_socket.sendto(message.encode(), (broadcast_address, broadcast_port))
print('Broadcast message sent: ', message)
while True:
    try:
        sender_socket.settimeout(5.0)
        data, server = sender_socket.recvfrom(4096)
        print('Received response from {}: {}'.format(server, data.decode()))
        list = server
    except socket.timeout:
        print('No more responses, exiting.')
        break

print ('Discovered receivers: ', list)
sender_socket.close()
