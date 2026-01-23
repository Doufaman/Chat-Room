# Chat Room 项目说明
## 留言
——Shu Ruiyi<br>
README_CN 第一版完全由我完成，主要包含我写代码时用到的配制（已填写）和我觉得后续需要填写的（未填写，只写了标题）。
## 运行方法
### Server
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
信息类型|信息内容<br>
WHO_IS_LEADER

### others
BUFFER_SIZE = 1024

## 文件说明

## 变量说明

## API说明