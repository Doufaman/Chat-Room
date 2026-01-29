# Chat Room 项目 - 集成版本

## 概述
1. **Leader 选举** - 使用 Bully 算法
2. **聊天功能** - Vector Clock
3. **容错机制** - 自动检测 Leader 故障并重新选举
4. **成员管理** - 服务器和客户端管理

## 架构

### 核心模块
- **common/** - 共享协议和 Vector Clock
  - `protocol.py` - 消息协议定义
  - `vector_clock.py` - 因果序时钟

- **network/** - 网络通信
  - `network_manager.py` - TCP/UDP 通信管理

- **server/** - 服务器端
  - `consensus.py` - Bully 算法实现
  - `chatroom_manager.py` - 聊天室管理
  - `membership.py` - 成员管理
  - `roles/` - Leader/Follower 角色

- **client/** - 客户端
  - `client.py` - 带因果序的聊天客户端

## 运行方法

### 1. 启动服务器

每个服务器需要一个唯一的 ID (1-5)：

```bash
# 终端 1 - 启动 Server 1
cd Chat-Room
python main.py 1

# 终端 2 - 启动 Server 2  
python main.py 2

# 终端 3 - 启动 Server 3
python main.py 3
```

**服务器会自动：**
- 进行 Leader 选举（ID 最大的成为 Leader）
- 监听客户端连接
- 处理 Leader 故障转移

### 2. 启动客户端

客户端连接到任意服务器：

```bash
# 终端 4 - Alice 连接到 Server 1
cd Chat-Room
python client/client.py Alice 1

# 终端 5 - Bob 连接到 Server 2
python client/client.py Bob 2

# 终端 6 - Charlie 连接到 Server 3
python client/client.py Charlie 3
```

**参数说明：**
- 第一个参数：用户名
- 第二个参数：要连接的服务器 ID

## 配置说明

### 服务器配置 (server/config.py)

```python
SERVERS = [
    {"id": 1, "host": "127.0.0.1", "tcp_port": 5001, "udp_port": 6001},
    {"id": 2, "host": "127.0.0.1", "tcp_port": 5002, "udp_port": 6002},
    {"id": 3, "host": "127.0.0.1", "tcp_port": 5003, "udp_port": 6003},
]

CLIENT_PORT_BASE = 8000  # Server 1 监听 8001，Server 2 监听 8002...
```

### 端口使用

| 端口范围 | 用途 | 协议 |
|---------|------|------|
| 5001-5005 | 服务器间心跳 (Consensus) | TCP |
| 6001-6005 | 服务器间选举 (Bully) | UDP |
| 8001-8005 | 客户端连接 | TCP |

## 功能特性

### 1. Leader 选举（Bully 算法）
- **自动选举**：启动时自动选出 ID 最大的服务器作为 Leader
- **故障检测**：通过心跳检测 Leader 是否存活
- **自动恢复**：Leader 崩溃后自动重新选举

### 2. 因果序消息传递
- **Vector Clock**：每个客户端维护向量时钟
- **消息排序**：确保消息按因果顺序传递
- **Hold-back Queue**：暂存不满足因果序的消息

### 3. 聊天功能
- **JOIN**：新用户加入通知所有人
- **CHAT**：发送消息到聊天室
- **广播**：服务器转发消息给所有客户端

## 测试场景

### 场景 1: 正常聊天
1. 启动 3 个服务器
2. 启动 3 个客户端
3. 各客户端发送消息
4. 验证所有消息按因果序到达

### 场景 2: Leader 故障
1. 启动 Server 1, 2, 3（Server 3 成为 Leader）
2. 连接客户端
3. Ctrl+C 关闭 Server 3
4. 观察 Server 2 自动成为新 Leader
5. 验证聊天功能继续工作

### 场景 3: 因果序验证
1. Alice 发送 "Hello"
2. Bob 收到后回复 "Hi Alice"
3. Charlie 应该先看到 "Hello"，再看到 "Hi Alice"

## 调试

### 查看日志
所有服务器和客户端输出详细日志：
- `[Consensus]` - 选举相关
- `[Leader]` - Leader 行为
- `[Follower]` - Follower 行为
- `[ChatroomManager]` - 聊天室事件
- `[DEBUG]` - 消息缓存和因果序

### 常见问题

**Q: 端口被占用**
A: 修改 `config.py` 中的端口配置

**Q: 客户端连接失败**
A: 确保对应的服务器已启动

**Q: 消息乱序**
A: 检查 Vector Clock 是否正确更新（看 DEBUG 日志）

## 技术细节

### 消息格式

**服务器间消息（UDP）：**
```json
{
  "type": "ELECTION | ANSWER | COORDINATOR | HEARTBEAT",
  "sender": 1
}
```

**客户端消息（TCP）：**
```json
{
  "type": "JOIN | CHAT | LEAVE",
  "sender": "Alice",
  "vector_clock": {"Alice": 1, "Bob": 0},
  "content": "Hello!"
}
```

### 状态机

**服务器状态：**
- FOLLOWER → 监听 Leader 心跳
- ELECTION → 进行选举
- LEADER → 发送心跳，处理客户端

**客户端消息处理：**
1. 收到消息
2. 检查因果序条件
3. 可传递？→ 显示，否则 → 放入缓存
4. 重新检查缓存
