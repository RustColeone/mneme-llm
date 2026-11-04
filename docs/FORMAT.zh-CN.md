# mneme-llm 文件格式（结构 2）

[English](FORMAT.md) · **简体中文**

mneme-llm 文件是一个 SQLite 3 数据库。仅凭本页内容，就足以用任何语言
读写这样的文件。Python 包只是其中一种实现；下文不依赖它。

时间采用 Unix 秒（浮点数，UTC）。文本为 UTF-8。向量是小端序的
float32 数组，归一化到长度为 1。`meta.schema_version` 为 `2`：
读取方必须拒绝任何其他版本的文件。
`python -m mneme_llm.migrate FILE` 会把结构 1 的文件升级到当前版本。

## 表

### `memories`：笔记

| 列 | 类型 | 含义 |
|---|---|---|
| `id` | 整数 | 主键 |
| `space` | 文本 | 这是谁的记忆（一个应用或角色） |
| `subject` | 文本 | 笔记是关于谁的 |
| `key` | 文本，可为 null | 关于什么，小写，`part(.part){0,3}`，最多 48 个字符；绝不是值本身 |
| `kind` | 文本 | `fact`、`preference`、`episode`、`plan` 或 `reflection` |
| `text` | 文本 | 笔记，一行，最多 500 个字符 |
| `importance` | 整数 | 1（琐碎）… 5（核心：始终在上下文中） |
| `feeling` | 实数 | −1 … 1，对象对此的感受（0：中性或未知） |
| `happened_at` | 实数 | 发生的时间（对于计划：计划发生的那一天） |
| `created_at` | 实数 | 写入的时间 |
| `recalled_at` | 实数，可为 null | 最后一次被证据回忆的时间 |
| `recalls` | 整数 | 被回忆的次数 |
| `superseded_by` | 整数，可为 null | 替换它的笔记的 id（同键） |
| `deleted_at` | 实数，可为 null | 被遗忘的时间 |
| `source` | 文本，可为 null | 谁写的：`auto`（模型，未经提示）、`user`、`cli`、`core-diary`… |
| `gloss` | 文本，可为 null | 用统一语言写的笔记（意思第 2 层），如果写了的话 |
| `folded` | 文本 | 对 `text` 做 Unicode 完整大小写折叠（并把 `i` + U+0307 读作 `i`）后的结果，用于重复检查 |

当 `superseded_by` 和 `deleted_at` 都为 null 时，笔记是**有效**的。写入一条带键的笔记，会把同一
`(space, subject, key)` 下的有效笔记的 `superseded_by` 设好，因此每个键至多只有一条有效笔记。
`text` 和 `gloss` 从不包含换行（写入时会折叠空白）。

同一对象的两条有效笔记绝不会具有相同的 `folded`，除非两者都有键且键不同。

### `vectors`：意思第 1 层

`(memory_id, embedder)` 主键；`vector`（blob）。`embedder` 指明模型及其设置
（`openai:text-embedding-3-small:256`）；来自不同 embedder 的向量从不比较。只有当笔记仍然存在、其文本就是
被嵌入的文本时才保存向量（已删除笔记的 id 会被复用），插入笔记的写入进程会删除其 id 下遗留的任何向量行。
已不存在的笔记的行会在 `purge` 和 `erase` 时删除。

### `profiles`：印象卡片

`(space, subject)` 主键，`text`，`updated_at`。几句话，显示在笔记上方。

### `moods`：当前状态

`(space, subject)` 主键；`value`（写入时为 0–100）；`emotions`（JSON 对象，情绪 → 强度 0–100）；
`updated_at`；`last_event`（`mood_events` 中的 id）；`told_event`（最后告诉模型的事件）。

存储的值是截至 `updated_at` 的值。要读取时刻 *t* 的状态，令 *h* = 距 `updated_at` 的小时数：

    value(t)   = baseline + (value − baseline) · 0.5^(h / 3)
    emotion(t) = emotion · 0.5^(h · 60 / 90)

基线（70）和两个半衰期都是设置，不属于文件。

### `mood_events`：时间线

`id`、`space`、`subject`、`at`、`delta`（实际应用的改变）、`value`（改变后的值）、`emotions`（JSON：
这个事件添加了什么）、`reason`（推动它的原因，用显示语言：判断模型的句子，或对方的原话；情绪从
`emotions` 告诉模型）、`confidence`（0–1）、`source`（`user`、`speak-up`、`duty`、`manual`…）、
`judge`（谁作的回答：宿主程序的聊天模型是 `prompt`，宿主程序自己的判断者则是它写在回答里的名字）。

### `relationships`：每个人对伙伴来说是谁

`(space, subject)` 主键；`role`（`creator`、`family`、`friend`、`acquaintance`，或宿主程序自定义的）；
`closeness`（0–100，截至 `updated_at`）；`since`（角色被赋予的时间）；`updated_at`（亲近度最后写入的
时间：赋予角色，或一个有来往的一天）。

每个空间至多一个 `creator`。使用内置区间时，亲近度保持在角色对应的区间内：创造者 80–100，家人
60–100，朋友 20–90，认识的人 0–60。要读取时刻 *t* 的亲近度，令 *d* = 距 `updated_at` 的天数：

    closeness(t) = min(ceiling, max(floor, closeness − d / 30))       (the creator's does not fade: d = 0)

区间是读取该值时宿主程序所持有的角色区间，因此收窄后的区间会把已经在其内的人保留下来。晚于
`updated_at` 的某个聊天日（见 `episodes.day`）有一次来往，就加 1，直到角色的上限；在 `updated_at` 之前的
时间（时钟被调回）有来往则什么也不改变。速率、区间和时区都是设置，不属于文件。

### `aliases`：每个人怎么称呼伙伴

`(space, subject)` 主键；`alias`（一行，最多 40 个字符，不能为空白）；`updated_at`（设定的时间）。没有
称呼的人没有这一行。

### `people`：一个人的几个主体

`(space, subject)` 主键；`person`（这个人的各行存放在哪个主体名下）。一行表示 `subject` 就是 `person`：
每个读者和写者在拿到 `subject` 时都改用 `person`，所以其他表不会在已链接的主体名下保存任何行。链接只有
一层：`person` 本身从不被链接，也从不等于 `subject`。链接会把 `subject` 名下的内容移到 `person` 名下：它的
笔记、检索词索引行和回忆日志（随后和导入之后一样，每个键只保留一条最新的有效笔记，同一段有效文本不出现
两次），它的心情时间线，以及它的对话连同索引和分布；两张印象卡、两份心情（连同事件链接）或两个称呼中
保留 `updated_at` 更新的那一个，两段关系中保留此刻更亲近的那一段（相同时保留这个人自己的），起始时间
`since` 取更早的一个，两个第一句话中保留这个人自己的。两个表层合而为一（见 `surfaces`）。没有这一行的主体
就是它自己这个人。

### `note_terms`：检索词索引

`(space, subject, term, memory_id)` 主键。一条有效笔记的行恰好是它的文本、键的各部分和译文的检索词，每个
检索词一行。改变其中任何一项的写入进程会替换该笔记的行；删除笔记的写入进程会删除它们；在复用的 id 下插入
笔记的写入进程会先删除其下遗留的任何行。`meta.terms_version` 指明建立这张表和 `episode_terms` 的分词器：
分词器不同的写入进程在搜索之前，会从文本重建这两张表，并更新它。不使用该索引的读取方可以忽略它，但写入
进程必须维护它。

### `episodes`：说过的话，逐字保留

| 列 | 类型 | 含义 |
|---|---|---|
| `id` | integer | 主键，自增：一个 id 绝不会用第二次，`surfaces.start_id` 依赖这一点 |
| `space` | text | 谁的记忆 |
| `subject` | text | 这段对话是和谁说的（这个人，与笔记相同） |
| `at` | real | 说的时间 |
| `day` | integer | 它的聊天日：`at − 4 小时` 在伙伴所在时区的日历日，用公历序数表示（公元 1 年 1 月 1 日是 1），保存时写入 |
| `conversation` | text | 在哪里说的：宿主程序给这个聊天起的名字（没有则为 `""`），至多 200 个字符 |
| `lines` | text | JSON `[[who, said], …]`：按顺序的这段对话，至多 40 行；`who` 是至多 80 个字符的一行（没有特定的人则为 `""`），`said` 至多 8,000 个字符（更长的保留开头和结尾） |
| `size` | integer | 它有多少个不同的检索词（BM25 的长度） |
| `tokens` | real | 模型大约算它多少词元：把各行写成 `who: said`、每行一条，中日韩字符每个 0.85，其他字符每个 0.3，再加 2.4；保存时写入 |
| `stability` | real | S，以天计：它淡忘得有多慢（起始为 30，至多 1,000,000） |
| `recalled_at` | real, null | 最近一次被重温的时间 |
| `recalls` | integer | 被重温的次数 |

一段对话的保留度是 `R = exp(−d / stability)`。它的最后一天是 `max(at, recalled_at)` 的聊天日；`d` 在那一天是
0，之后是 1 加上这个对象在那天之后、今天之前的聊天日数（`day` 的不同取值）。在比上一次更晚的聊天日重温一次，
会把 `stability` 设为 `stability · (1.5 + 3 · (1 − R))`（至多 1,000,000），把 `recalled_at` 设为重温的时间
（取两者中较晚的）；同一天的第二次什么也不改变。一段对话在被搜索找到时会被重温；同一对象后来的一段对话，
如果在意义上是离它最近的三段之一，并且比该对象的分布（`episode_spread`）中 98% 的配对都更近，也会重温它。
它的检索词取自各行说的话，不包括说话的人。对话会被直接删除（`forget`、`erase`），连同它在 `episode_terms` 和
`episode_vectors` 中的行。

### `episode_terms`、`episode_vectors`、`episode_spread`

`episode_terms` 是对话的检索词索引，维护方式与 `note_terms` 相同：主键 `(space, subject, term,
episode_id)`，对话中每个不同的检索词一行，并在 `episode_id` 上建有索引。`episode_vectors` 存放意义第 1
层给对话生成的向量：主键 `(episode_id, embedder)`，`vector`（blob）。生成向量的文本是写成文字的日期
`[08 May 2023, 13:56]`，下面是对话的各行 `who: said`。`episode_spread` 按 `(space, subject, embedder)`
记录该对象所有带向量的对话两两之间相似度的直方图：`bins`（200 个计数的 JSON 列表；第 `i` 格是从
`−1 + i/100` 起的相似度）和 `pairs`（它们的总和）。一对对话在两者中后一段得到向量时计入；一个对象要
积累到 100 对之后，才会按意义重温。

### `surfaces`：对话最新部分的起点

`(space, subject)` 主键；`start_id`（表层就是这个对象 `id` 大于它的那些对话）；`cleared_at`（最后一次清空的
时间，紧接在这个对象最晚的 `at` 之后；或者较早部分变成总结时，留下的第一段对话的 `at`）；`summary`（代替
已离开部分的总结，至多 8,000 个字符，没有则为 `""`）。没有这一行的对象，全部对话都在表层上。这里只保存起点：
表层的轮次就是对话本身，按 `id` 从新到旧读取，按 `at` 的顺序显示。

把 `old` 链接到 `person` 时，如果 `old` 有这一行或有任何对话：保留较低的 `start_id` 和 `cleared_at`（没有行算
作 0），总结合并并截到 8,000 个字符，既没有起点也没有总结的行会被删除。

### `first_prompts`：一个人说的第一句话

`(space, subject)` 主键；`text`（至多 8,000 个字符；被丢弃后为 `""`，这样下一条消息不会取代它：这个人没有第一句
话，但这一行留到 `erase`）；`at`；`by_command`（这个人亲自设置时为 1）；`send`（放在表层前面时为 1）。

### `recalls`：回忆日志

`id`、`space`、`subject`、`at`、`query`、`chosen`（JSON `[[id, why], …]`）、`skipped`（JSON
`[[id, reason], …]`）。每个对象保留最新的 200 条。

### `config`：伙伴的配置

`(space, key)` 主键；`value`（JSON）；`origin`（`default`、`file`、`set` 或 `import`）；`updated_at`。键
是扁平的：`companion.name`、`companion.display_language`、`companion.memory_language`（`""`：没有统一
语言）、`companion.zone`（`""`、`UTC+8` 或 IANA 名称）、`memory.*`、`mood.*`（心情的设置）、
`relations.liking`、`relations.growth`（旧文件里的，不再使用）、`relations.fade_days` 和 `relations.locked`（手动锁住的亲近度：主体对应的数值）、`roles` 和 `emotions`（各是一个对象列表，完整给出）、
`prompts.<name>`（给模型的提示词）和 `messages.<language>.<key>`（显示的语句）。`mneme-llm config template`
会打印每个键及其默认值；`docs/DESIGN.md` 第 12 节给出了规则。

一个空间的行会在该空间第一次打开时整批写入（先是默认值，然后配置文件覆盖它们），并且只在宿主程序
设置、应用或载入默认值时改变。在提示词和语句中，`{name}` 是占位符，一段文本只能使用其默认值中存在
的占位符；任何其他花括号都是字面量。读取方若发现它无法接受的值，应对该键使用自己的默认值并说明；
它不认识的键则保持原样。

### `meta`

`key`、`value`。保存 `schema_version`、`terms_version`（见 `note_terms`）、`floor:<embedder>` 以及宿主程序可设置
的 `adopted:…` 标志。

`floor:<embedder>` 是一个 JSON 对象：在这个文件里为该 embedder 模型测量到的内容。`floor` 是相似度
下限，低于它时笔记对查询什么也说明不了；`version` 是内置的校准集的版本（另一版本的记录会重新测量）；
`separated` 说明该集合的相关配对是否明显高于其不相关配对（如果不是，`floor` 就是默认值）；`set`
保存该集合的 `floor`、相关配对的下四分位数（`related`）、不相关配对的第 95 百分位数（`unrelated`）
以及其不相关笔记配对的中位数相似度（`background`）；`file` 为 null，或保存文件自身笔记上次比较时的
最高笔记 id（`at`）、比较了多少条（`notes`），以及在数量足够时它们的中位数相似度（`background`）和
它造成的移动量（`shift`）。

## 导出格式

`Mneme.export_data()` / `mneme-llm export` 会写出一个 JSON 对象：

```json
{"mneme_llm": 2, "space": "dafeiyu", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", "gloss": null, …}],
 "profiles": [...], "moods": [...], "mood_events": [...], "relationships": [...], "aliases": [...],
 "people": [...], "episodes": [{"id": 1, "subject": "discord:42", "at": 1792885000.0, "conversation": "dm",
 "lines": [["Leo", "…"], ["大肥鱼", "…"]], "stability": 30.0, "recalled_at": null, "recalls": 0}],
 "surfaces": [{"subject": "discord:42", "cleared_at": 1792885000.0, "summary": "…"}],
 "first_prompts": [{"subject": "discord:42", "text": "…", "at": 1792880000.0, "by_command": 0, "send": 0}],
 "config": [{"key": "companion.name", "value": "大肥鱼", "origin": "file"}, …]}
```

各行就是表里的行，以对象的形式给出，不含 `folded`（对话的 `lines` 是一个列表，不含 `size`、`day` 和
`tokens`；表层不含 `start_id`，因为 id 在另一个文件里没有意义）。向量、下限和分布不导出：它们属于 embedder，
会在使用时重建或重新测量。导入时，记忆 id 会重新编号，
`superseded_by` 链接跟随新的编号；每条笔记都要遵守写作规则（单行、至多 500 个字符，空白折叠；
键转为小写，若不是至多 48 个字符的 `part(.part){0,3}` 就丢弃；未知的种类按 `episode` 读取；
重要度限制在 1–5，感受限制在 −1…1，`recalls` 限制为 0 或更大；不是 1970 年到 3000 年之间秒数的
时间会被替换（`created_at` 换成当前时间，其余换成 `created_at`）；不是文本的 `source` 被丢弃；
不是对象的一行，或没有 text 或 subject 的笔记会被跳过）；随后按对象处理：每个键下最新的
有效笔记保持有效，其余的都指向它；同一段有效文本出现两次时（按大小写折叠比较），保留带键的那
一份，否则保留第一份（其余标记为已删除）。心情导入时不带事件链接（时间线单独导入）；与时间线
中已有事件相同的事件不会重复添加。关系会替换对方现有的关系，其亲近度保持在角色对应的区间内
（宿主程序没有的角色为 0–100）；单人角色（比如第二个创造者）的第二个持有者会被跳过。对话要遵守保存
规则（各行如上，`at` 是以秒计的时间，`stability` 是正数，否则为 30；没有对象、时间或文字的会被跳过），
并得到新的 id、聊天日和词元数；已经存在的（同一个人、时间、对话和文字）不会重复添加。表层从这个对象在
`cleared_at` 之前说的最后一段对话开始，已有表层时按链接的方式合并；已有的第一句话保留，被丢弃的（`""`）
仍然是丢弃的。链接按链接的方式
加入（文件里已经链接到另一个人的主体保持原来的链接），随后导入放在任何已链接主体名下的内容并入其本人。只有导入方
要求时才应用配置（其中的提示词是给导入方模型的指令），逐行应用，键未知或值未通过校验的行会被
跳过。

## 检索词

为了与 Python 实现的回忆效果（分词器版本 `4`）保持一致，文本会先做规范化：NFKC、Unicode
完全大小写折叠（其中 `i` + U+0307 读作 `i`，因此土耳其语 *İ* 能匹配 *i*）、U+2019 读作
撇号，并去掉希伯来文的元音符号（U+0591–U+05C7）和阿拉伯文的元音符号
（U+064B–U+065F、U+0670）。
之后，检索词是下面两种之一：

- 单词：由任意文种的字母、数字和组合标记（Unicode 类别 L、N、M）以及 `_` 组成的一串字符，
  两个字符之间允许出现撇号；去掉首尾的 `'`、`_` 和 `-`，去掉末尾的 `'s`，再要求长度不少于
  两个字符，并去掉常见的英语虚词；对 ASCII 单词，还会去掉表示复数的 `s`/`ies`；
- 在一串中文、日文、韩文字符中，或在一段不用空格书写的文字（泰文、老挝文、高棉文、
  缅甸文）中，每个相邻的两字组合（去掉 我们、什么 这类常见虚词组合）和每个单字
  （去掉 的、了 这类常见虚词字，以及组合标记）。

每个不同的检索词在每段文本中只计一次。如果安装并启用了 jieba，则会把 jieba 切出的两个
及以上字符的词也加入中日韩文字串（版本 `4+jieba`）。其他实现的分词方式可能不同；这只
影响一次查询能找回哪些笔记，不会影响存储的内容。

## 索引

索引不改变文件的含义；创建这些表的写入进程会把它们全部建好：`memories_live`（`(space, subject, deleted_at,
superseded_by)`）、`memories_key`（`(space, subject, key)`）、`memories_folded`（`(space, subject, folded)`）、
`memories_newest`（`(space, subject, id)`）、`memories_important`（`(space, subject, importance, id)`）、
`recalls_subject`（`(space, subject, at)`）、`mood_events_subject`（`(space, subject, at)`）、`people_person`
（`(space, person)`）、`note_terms_memory`（`memory_id`）、`episodes_subject`（`(space, subject, at)`）、
`episodes_conversation`（`(space, subject, conversation, at)`）、`episodes_day`（`(space, subject, day)`）、
`episodes_newest`（`(space, subject, id)`）和 `episode_terms_episode`（`episode_id`）。
