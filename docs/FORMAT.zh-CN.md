# mneme-llm 文件格式（结构 1）

[English](FORMAT.md) · **简体中文**

mneme-llm 文件是一个 SQLite 3 数据库。仅凭本页内容，就足以用任何语言
读写这样的文件。Python 包只是其中一种实现；下文不依赖它。

时间采用 Unix 秒（浮点数，UTC）。文本为 UTF-8。向量是小端序的
float32 数组，归一化到长度为 1。`meta.schema_version` 为 `1`：
读取方必须拒绝版本高于自己已知版本的文件，并且可以迁移版本较低的文件。
同一版本内新增的列见[结构 1 内的变更](#changes-within-schema-1)；
写入进程打开较旧的文件时会补上这些列。

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
| `gloss` | 文本，可为 null | 用统一语言写的笔记（意思第 3 层），如果写了的话 |
| `terms` | 文本，可为 null | 缓存：笔记的检索词，以空格分隔；任何时候都可能为 null |
| `folded` | 文本，可为 null | 缓存：对 `text` 做 Unicode 完整大小写折叠（并把 `i` + U+0307 读作 `i`）后的结果，用于重复检查；可能为 null |

当 `superseded_by` 和 `deleted_at` 都为 null 时，笔记是**有效**的。写入一条带键的笔记，会把同一
`(space, subject, key)` 下的有效笔记的 `superseded_by` 设好，因此每个键至多只有一条有效笔记。
`text` 和 `gloss` 从不包含换行（写入时会折叠空白）。

`terms` 属于写入它的分词器（`meta.terms_version`）；分词器不同的读取方会把每个 `terms` 设为 null
（并清空 `note_terms`），并在使用时重建它们。修改 `text`、`gloss` 或 `key` 的写入进程会把 `terms`
设为 null，并删除该笔记的 `note_terms` 行。
`folded` 在写入时填充；比较文本的写入进程会先填充该对象任何为 null 的 `folded`。同一对象的两条
有效笔记绝不会具有相同的 `folded`，除非两者都有键且键不同。

### `vectors`：意思第 1 层

`(memory_id, embedder)` 主键；`vector`（blob）；`taught`（文本，可为 null：这个向量教给词向量中心的
检索词，以空格分隔，可能为空；没有教过任何东西时为 null）。`embedder` 指明模型及其设置
（`openai:text-embedding-3-small:256`）；来自不同 embedder 的向量从不比较。已不存在的笔记的行会在
`purge` 和 `erase` 时删除。

### `meaning_terms`：意思第 2 层

`(embedder, term)` 主键；`count`（包含该检索词的学习过的笔记数）；`vector`（blob：那些笔记向量的
滑动平均值，未重新归一化）。只学习笔记，从不学习查询。`meta."meaning_texts:<embedder>"` 记录已学习
的笔记数，始终等于该 embedder 的 `taught` 不为 null 的向量数（读取方若发现不符，或发现某个检索词
没有任何被教过的东西，就重置该 embedder 的词向量中心），而 `meta."meaning_version:<embedder>"` 指明
拆分其检索词的分词器；分词器不同时，这些行不会被使用，下一次学习会先删除它们。

教一条笔记的写入进程会在一个事务里添加向量行、每个检索词的新滑动平均值，以及 `taught` 中的检索词；
前提是该笔记仍然存在、其文本就是被嵌入的文本（已删除笔记的 id 会被复用），并且它还没有来自该
embedder 的向量。插入笔记的写入进程会删除其 id 下遗留的任何向量行。删除笔记的写入进程会先收回其
每个向量教过的东西：对 `taught` 中的每个检索词，`count` 减一，平均值变为
`(mean · count − vector) / (count − 1)`，当 `count` 变成 0 时该行删除；`meaning_texts` 减一。这不需要
分词器。不运行这一层的实现，在删除笔记时仍必须这样做，否则已删除笔记的词会留在文件里。重置某个
embedder 的词向量中心会删除它的行和两个 meta 键，并把它的向量的 `taught` 设为 null；这些向量会从
文件里重新被教。

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
`judge`（作出回答的一层或多层，其中置信度最先被计入的那一个：`luna`、`luna+prompt`）。

### `relationships`：每个人对伴侣来说是谁

`(space, subject)` 主键；`role`（`creator`、`family`、`friend`、`acquaintance`，或宿主程序自定义的）；
`closeness`（0–100，截至 `updated_at`）；`since`（角色被赋予的时间）；`updated_at`（亲近度最后写入的
时间：赋予角色，或一个有来往的一天）。

每个空间至多一个 `creator`。使用内置区间时，亲近度保持在角色对应的区间内：创造者 80–100，家人
60–100，朋友 20–90，认识的人 0–60。要读取时刻 *t* 的亲近度，令 *d* = 距 `updated_at` 的天数：

    closeness(t) = min(ceiling, max(floor, closeness − d / 30))       (the creator's does not fade: d = 0)

区间是读取该值时宿主程序所持有的角色区间，因此收窄后的区间会把已经在其内的人保留下来。晚于
`updated_at` 的某一天（按伴侣所在时区）有一次来往，就加 1，直到角色的上限；在 `updated_at` 之前的
时间（时钟被调回）有来往则什么也不改变。速率、区间和时区都是设置，不属于文件。

### `aliases`：每个人怎么称呼伴侣

`(space, subject)` 主键；`alias`（一行，最多 40 个字符，不能为空白）；`updated_at`（设定的时间）。没有
称呼的人没有这一行。

### `people`：一个人的几个主体

`(space, subject)` 主键，并在 `(space, person)` 上有索引；`person`（这个人的各行存放在哪个主体名下），
`updated_at`（链接的时间）。一行表示 `subject` 就是 `person`：每个读者和写者在拿到 `subject` 时都改用
`person`，所以其他表不会在已链接的主体名下保存任何行。链接只有一层：`person` 本身从不被链接，也从不
等于 `subject`。链接会把 `subject` 名下的内容移到 `person` 名下：它的笔记、检索词索引行和回忆日志（随后
和导入之后一样，每个键只保留一条最新的有效笔记，同一段有效文本不出现两次），以及它的心情时间线；两张
印象卡、两份心情（连同事件链接）或两个称呼中保留 `updated_at` 更新的那一个，两段关系中保留此刻更亲近
的那一段（相同时保留这个人自己的），起始时间 `since` 取更早的一个。没有这一行的主体就是它自己这个人。

### `note_terms`：检索词索引

`(space, subject, term, memory_id)` 主键，并在 `memory_id` 上有索引。一条笔记的行恰好是它的
`memories.terms` 中的检索词，每个检索词一行；`terms` 为 null 的笔记没有行。把 `terms` 设为 null 的
写入进程（新的译文、新的键、另一个分词器）会删除该笔记的行；删除笔记的写入进程也会删除它们；在
复用的 id 下插入笔记的写入进程会先删除其下遗留的任何行。不使用该索引的读取方可以忽略它，但写入
进程必须维护它。

### `episodes`：说过的话，逐字保留

| 列 | 类型 | 含义 |
|---|---|---|
| `id` | integer | 主键 |
| `space` | text | 谁的记忆 |
| `subject` | text | 这段对话是和谁说的（这个人，与笔记相同） |
| `at` | real | 说的时间 |
| `conversation` | text | 在哪里说的：宿主程序给这个聊天起的名字（没有则为 `""`），至多 200 个字符 |
| `lines` | text | JSON `[[who, said], …]`：按顺序的这段对话，至多 40 行；`who` 是至多 80 个字符的一行（没有特定的人则为 `""`），`said` 至多 8,000 个字符（更长的保留开头和结尾） |
| `size` | integer | 它有多少个不同的检索词（BM25 的长度） |
| `stability` | real | S，以天计：它淡忘得有多慢（起始为 30，至多 1,000,000） |
| `recalled_at` | real, null | 最近一次被重温的时间 |
| `recalls` | integer | 被重温的次数 |
| `terms` | text, null | 缓存：它的检索词，以空格分隔 |

一段对话在时间 `t` 的保留度是 `R = exp(−(t − max(at, recalled_at)) / (stability · 86400))`。在 `t`
重温一次，会把 `stability` 设为 `stability · (1.5 + 3 · (1 − R))`，把 `recalled_at` 设为 `t`（取两者中
较晚的）。一段对话在被搜索找到时会被重温；同一对象后来的一段对话，如果在意义上是离它最近的三段之一，
并且比该对象的分布（`episode_spread`）中 98% 的配对都更近，也会重温它。它的检索词取自每一行的 `who`
和 `said`。对话会被直接删除（`forget`、`erase`），连同它在 `episode_terms` 和 `episode_vectors` 中的行。

### `episode_terms`、`episode_vectors`、`episode_spread`

`episode_terms` 是对话的检索词索引，维护方式与 `note_terms` 相同：主键 `(space, subject, term,
episode_id)`，对话中每个不同的检索词一行，并在 `episode_id` 上建有索引。`episode_vectors` 存放意义第 1
层给对话生成的向量：主键 `(episode_id, embedder)`，`vector`（blob）。生成向量的文本是写成文字的日期
`[08 May 2023, 13:56]`，下面是对话的各行 `who: said`。`episode_spread` 按 `(space, subject, embedder)`
记录该对象所有带向量的对话两两之间相似度的直方图：`bins`（200 个计数的 JSON 列表；第 `i` 格是从
`−1 + i/100` 起的相似度）和 `pairs`（它们的总和）。一对对话在两者中后一段得到向量时计入；一个对象要
积累到 100 对之后，才会按意义重温。

### `recalls`：回忆日志

`id`、`space`、`subject`、`at`、`query`、`chosen`（JSON `[[id, why], …]`）、`skipped`（JSON
`[[id, reason], …]`）。每个对象保留最新的 200 条。

### `micro_models`：判断第 2 层

`question`（主键：`name:sha1(type|instructions|labels…|tokenizer version)[:12]`）、`kind`、`labels`（JSON
列表）、`weights`（JSON `{"bias": [...], "w": {"feature": [...]}, "window": [0/1…]}`）、`examples`、
`updated_at`。特征是检索词的 CRC-32 哈希，掩码到 18 位。不运行微型模型的实现可以忽略这张表。

### `config`：伴侣的配置

`(space, key)` 主键；`value`（JSON）；`origin`（`default`、`file`、`set` 或 `import`）；`updated_at`。键
是扁平的：`companion.name`、`companion.display_language`、`companion.memory_language`（`""`：没有统一
语言）、`companion.zone`（`""`、`UTC+8` 或 IANA 名称）、`memory.*`、`mood.*`（心情的设置）、
`relations.growth` 和 `relations.fade_days`、`roles` 和 `emotions`（各是一个对象列表，完整给出）、
`prompts.<name>`（给模型的提示词）和 `messages.<language>.<key>`（显示的语句）。`mneme-llm config template`
会打印每个键及其默认值；`docs/DESIGN.md` 第 12 节给出了规则。

一个空间的行会在该空间第一次打开时整批写入（先是默认值，然后配置文件覆盖它们），并且只在宿主程序
设置、应用或载入默认值时改变。在提示词和语句中，`{name}` 是占位符，一段文本只能使用其默认值中存在
的占位符；任何其他花括号都是字面量。读取方若发现它无法接受的值，应对该键使用自己的默认值并说明；
它不认识的键则保持原样。

### `meta`

`key`、`value`。保存 `schema_version`、`terms_version`、`meaning_texts:<embedder>`、
`meaning_version:<embedder>`、`floor:<embedder>` 以及宿主程序可设置的 `adopted:…` 标志。

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
{"mneme_llm": 1, "space": "dafeiyu", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", "gloss": null, …}],
 "profiles": [...], "moods": [...], "mood_events": [...], "relationships": [...], "aliases": [...],
 "people": [...], "episodes": [{"id": 1, "subject": "discord:42", "at": 1792885000.0, "conversation": "dm",
 "lines": [["Leo", "…"], ["大肥鱼", "…"]], "stability": 30.0, "recalled_at": null, "recalls": 0}],
 "config": [{"key": "companion.name", "value": "大肥鱼", "origin": "file"}, …]}
```

各行就是表里的行，以对象的形式给出，不含 `terms` 和 `folded`（对话的 `lines` 是一个列表，不含 `size`
和 `terms`）。向量、词向量中心、下限、分布和微型模型不导出：它们属于 embedder 和分词器，会在使用时重建或重新测量。导入时，记忆 id 会重新编号，
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
并得到新的 id。链接按链接的方式
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

## 结构 1 内的变更

在这些内容加入之前写入的文件仍按原样打开；写入进程会补上缺失的部分：

- `memories.gloss`、`memories.terms` 和 `memories.folded`（列），以及在
  `(space, subject, folded)` 上的索引 `memories_folded`；
- `vectors` 和 `meaning_terms`（表），以及 `vectors.taught`（列）和索引
  `vectors_untaught`（建在 `embedder` 上，条件是 `taught` 为 null）。在早于
  `vectors.taught` 的文件中，没有任何向量教过任何内容，而 `meaning_texts` 却
  表示并非如此，因此第一个读取进程会重置这些词向量中心（它们可能包含查询中的
  词，且无法撤回），并从已存储的向量重新学习它们；
- `note_terms`（表）和索引 `note_terms_memory`，以及在
  `(space, subject, id)` 上的索引 `memories_newest` 和在
  `(space, subject, importance, id)` 上的索引 `memories_important`。在早于检索词
  索引的文件中，每条笔记的 `terms` 是否为 null 都有可能；不为 null 的会在首次
  需要时建立索引（读取进程在使用索引之前，会为某个对象的任意有效笔记建立
  索引：该笔记的 `terms` 为 null，或者有检索词但没有任何行）；
- `relationships`（表），以及 `meta` 中的 `floor:<embedder>` 键。没有这些内容的
  文件没有角色（每个人仍和以前一样计数），下限也尚未测量；
- `config`（表）。没有行的空间会在下次打开时采用其配置（默认值以及宿主程序
  的配置文件）；
- `aliases`（表，mneme-llm 0.2）。没有它的文件没有称呼；mneme-llm 0.1 能打开
  带有这张表的文件，并且不会动它；
- `people`（表）及索引 `people_person`（mneme-llm 0.2）。没有它的文件不链接任何人。mneme-llm 0.1
  能打开带有这张表的文件，但不会读取它：已链接的主体在那里又成了独立的人，并且没有它的笔记；
- `episodes`、`episode_terms`、`episode_vectors` 和 `episode_spread`（表），以及索引 `episodes_subject`、
  `episodes_conversation` 和 `episode_terms_episode`（mneme-llm 0.3）。没有它们的文件没有保存任何对话；
  mneme-llm 0.1 和 0.2 能打开带有这些表的文件，并且不会动它们（那时它们的 `erase` 会把一个人的对话留在
  文件里）。
