Latest Updation: 2026-02-01

新的文件:
- common/ 
    - vector_clock.py: VectorClock 类，用于聊天室消息的因果排序 (Causal Ordering)。
- network/
    - chatting_messenger.py: 负责 Client 与 ChatServer 之间的 TCP 通信协议（消息类型：JOIN, CHAT, LEAVE），解决了 TCP 粘包问题。
- server/ 
    - roles/ 
        - server.py: 将原有的 Leader 和 Follower 类合并为 Server 类，通过内部状态变量切换角色，减少代码冗余。
    - election_manager.py: 实现 Bully 选举算法，负责节点发现、选举协调以及Heartbeat（携带 Chatroom 信息）。
    - chatroom.py: 单个聊天室实例，管理客户端连接、消息广播及向量时钟处理。
    - chatroom_manager.py: 管理服务器内的多个聊天室，Leader 在端口 9005 监听客户端 Discovery 请求，并聚合全网聊天室信息。
- utils/
    - ip_validator.py: 用于 macOS/Linux 的 IP 输入验证工具。
- main_client.py: 完整的聊天客户端，用 UDP 广播并从Leader服务器获取了聊天室信息、单一聊天室基于 TCP 连接， 使用 VectorClock 消息排序。

改动:
- Changed UUID:   self.server_id = uuid.uuid4().int % (10**9)  Bully算法比较id大小， UUID是字符串， 需要转化为int进行比较;
- TCP Sticking Problem: 为TCP数据增加了Header， NetworkManager处理TCP连接的时候， 直接用buffer(1024)可能会一次性接受到多个数据包， 而多个数据包没有封装会导致“TCP粘连”;
- 原先startEngine启动时已经调用了start(), 之前的Follower和Leader重复在内部调用导致错误;
- Follower&Leader -> Server, 用内部字符串变量区分; 
- network_manager.py: 增加了用于UDP单独传输的函数， 以及用于Client信息传递的TCP socket管理函数；

启动：
1. start servers:
run `python main_server.py`

2. start clients:
run  `python main_client.py` 


共享文档
https://docs.google.com/document/d/1lmXN_JAy_hXVs1ySy973mZlotTrwEimMhMNObHw6ab0/edit?usp=sharing
