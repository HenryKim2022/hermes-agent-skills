# 跨组织参会者搜索实战指南

## 场景：全体研发团队 + 关联组织北京武汉

这是一个典型的"全员参会"场景，需要跨本企业和关联组织搜索参会者。

### 本企业研发团队

通过 `--query "研发"` + `--has-enterprise-email` 找到：

| 部门 | 典型成员 |
|------|---------|
| 研发中心 | Ray Sun |
| 北京研发部 | Ava Li |
| 武汉研发部 | Bruce Lee、黄迎兵、Wang Wei、Wang Qi |

### 关联组织（跨租户）

关联组织成员**没有企业邮箱**，必须用组织名称搜索。

#### 北京万云博华（10+人）

```bash
# 搜组织名
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --query "万云博华" --as user --page-size 30

# 研发关键词补漏（有些用户只有这个能搜到）
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --query "研发" --as user --page-size 30
```

两个搜索词结果**差异可能很大**，必须合并去重。

典型成员：张佳奇、王俊峰、张乐、刘立祥、孙琦、罗湘儒、郭赫伟、赵江波、王嘉旺、李建海、李增园、张卫震、茆洪铭、刘训、张天洁、王慧仙、郑伟、郭中华、李坤、雍蒙蒙

#### 万博智云武汉（2人）

```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --query "万博智云" --as user --page-size 30
```

典型成员：王炜、李细鹏

### 用户提名补漏

当用户说"某某某人没加上"时，直接用名称搜：

```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --query "刘立祥" --as user --page-size 30
```

注意可能有**同名不同租户**的多个结果（本企业 + 跨租户），需要全部加入。

### 邀请到会议

```bash
# 追加参会者
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli calendar +update \
    --event-id "<event_id>" \
    --add-attendee-ids "ou_xxx,ou_yyy,ou_zzz,..." \
    --as user

# 跨租户 open_id 和本企业 open_id 完全兼容，一起传入即可
```

### 规则总结

1. 永远不要只依赖单一搜索条件
2. 至少跑 2-3 个不同维度的搜索（组织名、部门名、common keyword）
3. 用户提到名字时，直接 name search → 加到会议
4. 跨租户用户直接加，飞书会议支持跨组织邀请