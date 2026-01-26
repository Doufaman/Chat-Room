为了让你的 Demo1 既能跑通，又符合分布式系统课程的“优雅”标准，我建议你采用 **“模块化解耦”** 的方式组织代码。

这种结构不仅方便你现在调试 Vector Clock，也为你以后可能扩展到 Demo2（多服务器或集群）打好基础。

---

Server:
Main Thread: for listening to newly joined client, then creates a unique thread for it
Unique Thread: especially for listening to certain client with TCP connection 
Global Queue 
Get message from unique thread
Give message to multicast thread 
Multicast Thread: fetch the messages from global queue and send messages to all clients 

### 1. 推荐的仓库目录结构

你可以按照功能逻辑将代码分为：**协议定义**、**网络层包装**、以及**业务逻辑（Server/Client）**。

```text
Stuttgart_Chat_Project/
│
├── common/                # 公共模块：所有端通用的逻辑
│   ├── __init__.py
│   ├── vector_clock.py    # VectorClock 类（包含自增、合并、比较逻辑）
│   └── protocol.py        # 消息格式定义（JSON 结构封装）
│
├── network/               # 网络接口：对 TCP Socket 的简单封装
│   ├── __init__.py
│   └── messenger.py       # 负责发送/接收长度前缀的 JSON 数据包
│
├── server/                # 服务端逻辑
│   ├── __init__.py
│   └── main.py            # 服务器启动入口与 Client 线程管理
│
├── client/                # 客户端逻辑
│   ├── __init__.py
│   └── main.py            # 客户端启动入口、UI/输入线程、Hold-back Queue
│
└── run_demo.py            # 自动化脚本：一键启动 1 Server + 3 Clients

```

---

### 2. 关键模块设计提示

#### A. 抽象通信接口 (`network/messenger.py`)

不要在业务逻辑里直接操作 `socket.send()`。由于 TCP 是流协议，可能会出现“粘包”问题。

> **提示**：编写一个接口，在每个 JSON 消息前加上 4 字节的长度前缀（Header），确保 `recv` 能完整取出一个 JSON。

```python
# 核心接口示意
def send_msg(sock, data_dict):
    # 将字典转为 JSON 字节，计算长度并发送
    ...

def recv_msg(sock):
    # 先读 4 字节取长度，再读对应长度的字节转为字典
    ...

```

#### B. 向量时钟类 (`common/vector_clock.py`)

将向量时钟封装成一个类，这样在 Client 里只需要调用方法。

* `increment(user_id)`: 发信前调用。
* `is_deliverable(msg_vc, user_id)`: 接收时判断是否满足交付条件。
* `update(msg_vc)`: 交付后合并时钟。

#### C. 服务端与客户端的“创建函数”

根据你的要求，单独写调用创建函数。

* **Server 端**：`create_server(host, port)`。它应该返回一个 Server 对象，内部启动一个监听线程。
* **Client 端**：`create_client(server_host, server_port, username)`。它应该处理连接握手，并初始化该 Client 的本地 `local_vc`。

---

### 3. 如何实现 Hold-back Queue

在你的 `client/main.py` 中，组织代码时要有一个**“分水岭”**：

1. **接收线程**：只负责从 `network` 接口取数据，然后丢进一个 `incoming_buffer`。
2. **处理循环（核心）**：
* 不断检查 `buffer`。
* 如果发现满足交付条件（通过 `VectorClock.is_deliverable`）。
* **Deliver！**（打印消息，更新本地时钟）。
* **触发递归检查**：一旦递交了消息，必须重新检查 `buffer` 里的所有消息，看有没有之前被扣留的消息现在可以释放了。



---

### 4. 自动化演示脚本 (`run_demo.py`)

为了方便演示 1 Server + 3 Clients，写一个简单的 Python 脚本，使用 `subprocess` 同时拉起 4 个终端。

```python
import subprocess
import time

# 启动 Server
subprocess.Popen(["python", "server/main.py"])
time.sleep(1) # 等待服务器启动

# 启动 3 个不同名字的 Client
users = ["Alice", "Bob", "Charlie"]
for user in users:
    subprocess.Popen(["python", "client/main.py", user])

```

---

### 💡 给你的额外小贴士（Stuttgart Style）

既然你在做 Demo1，建议在 `protocol.py` 中给消息加一个 **`type`** 字段。

* `type: "CHAT"`: 普通聊天消息。
* `type: "JOIN"`: 新人加入，让 Server 广播给所有人，这样大家的 Vector Clock 字典才能动态添加新的 Key。

**这个代码组织架构是否符合你对“单独接口”和“单独调用”的想象？如果需要，我可以为你提供一个更具体的 `VectorClock` 类实现逻辑。**