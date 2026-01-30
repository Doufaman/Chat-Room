# Chat Room 项目说明
## 留言
——Shu Ruiyi<br>
README_CN 提供关于我这部分代码的说明。<br>
目前实现动态发现（除注册外）的功能，即server启动发送WHO_IS_LEADER寻找leader，根据有无回复选择初始化为leader或follower<br>
目前正在做的：<br>
尝试解决自定义IP问题，role切换功能，注册功能
## 运行方法
### Server
在终端运行，输入自定义IP
### Client

## 配制说明
默认所有设备在同一局域网(LAN)内
### IP配制
#### Server IP (静态)
测试使用的server IP：<br>
192.168.1.101<br>
192.168.1.102<br>
……

#### Client IP (动态)
随意设置，不要用特殊IP

#### others
broadcast: 192.168.1.255（针对测试IP）或255.255.255.255
multicast: 224.0.0.100

### port配制
未完成所有配制，暂时只考虑server之间的通信，不考虑client，比如可能每个群里需要一个port
#### 9000: UDP Broadcast广播监听端口
所有server和client监听
#### 9001：TCP Unicast 客户端
所有server监听，用于获取client信息
#### 9002：UDP Multicast 服务器内部端口
所有server监听，用于server内部通信<br>
暂定server启动时广播也用这个

### Message
以 | 分隔，|前后无空格<br>
信息类型|信息内容|自定义IP<br>
以下为信息类型和解释<br>
WHO_IS_LEADER: 新启动的服务器查询是否有正在运行的leader<br>
I_AM_LEADER: leader给新启动的server和client发送基本信息

### others
BUFFER_SIZE = 1024

## 文件说明
server.py: 服务器启动文件，包括dynamic_discovery函数<br>
network_manager: 提供3种类型的信息收发功能，针对message的encode和decode，可能有bug<br>
leader.py: leader相关逻辑<br>
follower.py: follower相关逻辑<br>

## 变量说明
ip_local和MY_IP指自定义IP，socket中出现的addr指自动获取的本机IP

## API说明
