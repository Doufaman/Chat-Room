This is a project from the Distributed Systems I course in the 25W semester at the University of Stuttgart.<br>
This project implements a distributed chatroom system with multiple clients and multiple servers. <br>
## Client Actions
1. creat new chatrooms
2. join and leave chatrooms
3. chat in chatrooms. 
## Server-Side Capabilities
1. dynamic discovery
2. fail stop fault tolerance
3. fault detection (heartbeat)
4. leader election (bully algorithm)
5. ordered reliable multicast (vector clock, causal ordering)
6. chat history backup and chat room recovery
## How to Run the Project
1. Launch [main_server.py]
2. Launch [main_client.py] when server is active
3. Detailed guidance will appear automatically upon startup.
