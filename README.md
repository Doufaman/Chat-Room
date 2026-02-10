**更新**: 2026-02-10

更新:
选举过程：
- Bully 算法：ID 最大的节点成为 Leader， 但因为存在心跳延迟， 导致不同follower开始选举的时刻不同， 因此第一个当选的也优先leader
- Leader 心跳超时触发重新选举
- 防脑裂：选举期间暂停心跳超时检查， 进入选举状态

聊天室管理:
- 所有 Server 维护 `chatroom_list` 字典（类似 `membership_list`）
- Leader 创建聊天室并广播 `NEW_CHATROOM` 给所有 Server
- ChatRoom 实例通过回调通知 Server 客户端数量变化
- Server 广播 `UPDATE_CHATROOM` 同步在线人数


客户端功能：
1. 自动广播查找 Leader
2. 获取聊天室列表
3. 创建新聊天室
4. 加入聊天室并开始聊天
5. 消息显示 VectorClock 调试信息
