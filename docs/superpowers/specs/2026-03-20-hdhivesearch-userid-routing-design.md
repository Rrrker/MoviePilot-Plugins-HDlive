# HDHiveSearch 用户消息路由修复设计

## 问题描述

**现象**：当任何用户发送影片名+？时，所有用户都收到搜索结果回复。

**根本原因**：MoviePilot WeChat 渠道的消息路由可能存在问题，导致消息广播给所有用户而非仅发送给请求者。

根据 MESSAGE_REPLY_GUIDE.md 的指导原则：
- 必须传 userid 确保消息发给正确用户
- 如果不传 userid 参数，消息可能无法正确发送给用户

## 设计方案

### 核心逻辑

| 情况 | 处理方式 |
|------|----------|
| userid 有效 | 只发给请求者（`post_message(..., userid=userid)`） |
| userid 为空 | 广播给所有用户（`post_message(..., userid=None)`）作为降级方案 |

### 修改点

#### 1. `handle_user_message` 方法（line 636）

**现状**：直接使用 `event_data.get('userid') or event_data.get('user')` 提取 userid

**修改**：
- 添加调试日志，记录 userid 和 channel 的值
- 如果 userid 为空，记录警告日志

```python
@eventmanager.register(EventType.UserMessage)
def handle_user_message(self, event: Event):
    if not self._enabled or not self._api:
        return

    event_data = event.event_data
    if not event_data:
        return

    text = event_data.get('text', '').strip()
    if not text:
        return

    channel = event_data.get('channel')
    userid = event_data.get('userid') or event_data.get('user')

    # 添加调试日志
    logger.info(f'[HDHiveSearch] 收到消息 - channel={channel}, userid={userid}, text={text}')

    # 检查 userid 是否有效
    if not userid:
        logger.warning(f'[HDHiveSearch] userid 为空，消息将广播给所有用户')

    # ... 后续处理逻辑不变 ...
```

#### 2. `_send_message` 方法（line 1366）

**现状**：无条件调用 `post_message(..., userid=userid)`

**修改**：添加日志确认调用参数

```python
def _send_message(self, channel, userid, title: str, text: str):
    if self._notify:
        logger.info(f'[HDHiveSearch] 发送消息 - channel={channel}, userid={userid}, title={title}')
        self.post_message(
            channel=channel,
            title=title,
            text=text,
            userid=userid
        )
```

### 行为对比

| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| userid=li., channel=wechat | 可能广播给所有 | 只发给 li.（取决于 MoviePilot 行为） |
| userid=None | 广播给所有 | 广播给所有 + 警告日志 |

## 实施步骤

1. 在 `handle_user_message` 中添加 `userid` 和 `channel` 的调试日志
2. 在 `_send_message` 中添加调用参数日志
3. 测试验证：用户A搜索，用户A收到结果，其他用户不收到

## 预期效果

- 当 MoviePilot WeChat 渠道正确支持 userid 路由时：消息只发给请求者
- 当 userid 为空时：消息广播给所有用户（降级方案）
- 添加的日志有助于后续排查问题