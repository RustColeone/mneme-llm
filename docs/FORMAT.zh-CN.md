# mneme-llm 文件格式（结构 1）

[English](FORMAT.md) · **简体中文**

mneme-llm 文件是一个 SQLite 3 数据库。仅凭本页就足以用任意语言读写
mneme-llm 文件。Python 包只是其中一种实现；下文不依赖它。

时间均为 Unix 秒（浮点数，UTC）。文本为 UTF-8。向量为小端序 float32
数组，归一化到长度 1。`meta.schema_version` 为 `1`：读取方必须拒绝
版本高于自身所知的文件，并可以对较低版本的文件执行迁移。同一版本内
新增的列列于[结构 1 内的变更](#changes-within-schema-1)之下；写入方
打开较旧的文件时会补上这些列。

## 数据表

### `memories`：笔记

| 列 | 类型 | 含义 |
|---|---|---|
| `id` | integer | 主键 |
| `space` | text | 谁的记忆（某个应用或角色） |
| `subject` | text | 这条笔记是关于谁的 |
| `key` | text, null | 这条笔记讲的是什么，小写，`part(.part){0,3}`，最多 48 个字符；绝不是值本身 |
| `kind` | text | `fact`、`preference`、`episode`、`plan` 或 `reflection` |
| `text` | text | 笔记本身，一行，最多 500 个字符 |
| `importance` | integer | 1（无关紧要）… 5（核心：始终放进上下文） |
| `feeling` | real | −1 … 1，对象当时对此的感受（0：中性或未知） |
| `happened_at` | real | 事情发生的时间（对计划而言：计划发生的那一天） |
| `created_at` | real | 写下的时间 |
| `recalled_at` | real, null | 最后一次因证据被回忆的时间 |
| `recalls` | integer | 被回忆了多少次 |
| `superseded_by` | integer, null | 取代它的那条笔记的 id（键相同） |
| `deleted_at` | real, null | 被遗忘的时间 |
| `source` | text, null | 谁写的：`auto`（模型主动写的）、`user`、`cli`、`core-diary`… |
| `gloss` | text, null | 用统一语言写的这条笔记（意思层 3），前提是写了的话 |
| `terms` | text, null | 缓存：这条笔记的检索词，以空格分隔；任何时候都可能为 null |
| `folded` | text, null | 缓存：做过 Unicode 完整大小写折叠的 `text`（并把 `i` + U+0307 读作 `i`），用于查重；可能为 null |

当 `superseded_by` 和 `deleted_at` 都为 null 时，这条笔记是**有效**笔记。写入一条带键的笔记时，
会把同一 `(space, subject, key)` 的有效笔记的 `superseded_by` 置为这条新笔记，因此每个键至多只有
一条有效笔记。`text` 和 `gloss` 从不包含换行（写入时会合并空白）。

`terms` 属于写它的那个分词器（`meta.terms_version`）；分词器不同的读取方会把所有 `terms` 置为 null
（并清空 `note_terms`），在使用时再重建。改动 `text`、`gloss` 或 `key` 的写入方会把 `terms` 置为
null，并删除这条笔记的 `note_terms` 行。`folded` 在写入时填入；需要比较文本的写入方会先补上该对象
所有为 null 的 `folded`。同一对象的两条有效笔记的 `folded` 绝不会相同，除非两条笔记都有键且键不同。

### `vectors`：意思层 1

`(memory_id, embedder)` 为主键；`vector`（blob）；`taught`（text，null：这个向量教给词向量中心的
检索词，以空格分隔，可能为空；没教过任何东西时为 null）。`embedder` 是模型及其设置的名称
（`openai:text-embedding-3-small:256`）；不同 embedder 的向量从不互相比较。已不存在的笔记的向量
行会在 `purge` 和 `erase` 时删除。

### `meaning_terms`：意思层 2

`(embedder, term)` 为主键；`count`（包含该检索词的已学笔记数）；`vector`（blob：这些笔记向量的滚动
平均值，未重新归一化）。只学笔记，从不学查询。`meta."meaning_texts:<embedder>"` 记录已学的笔记数，
始终等于该 embedder 的向量中 `taught` 不为 null 的个数（读取方若发现不是这样，或发现某些检索词没
教过任何东西，就会重置该 embedder 的词向量中心）；`meta."meaning_version:<embedder>"` 则是拆分这些
检索词的分词器的名称；若分词器不同，这些行不会被使用，下一次学的时候会先把它们删掉。

教一条笔记的写入方会在同一个事务里加入向量行、每个检索词的新滚动平均值以及 `taught` 中的检索词；
而且只有在这条笔记仍然存在、文本仍是当初被向量化的那段（已删除笔记的 id 会被复用），并且它还没有
该 embedder 的向量时才这么做。插入笔记的写入方会删除该 id 下残留的任何向量行。删除笔记的写入方会
先收回它每个向量所教的东西：对 `taught` 中的每个检索词，`count` 减一，平均值变为
`(mean · count − vector) / (count − 1)`，`count` 减到 0 时该行删掉；`meaning_texts` 减一。这个过程
不需要分词器。不运行这一层的实现，在删除笔记时仍必须这样做，否则被删笔记的词会留在文件里。重置某个
embedder 的词向量中心会删掉它的行和两个 meta 键，并把它各向量的 `taught` 置为 null；这些向量会从
文件里重新教一遍。

### `profiles`：印象卡片

`(space, subject)` 为主键，`text`，`updated_at`。几句话，显示在笔记上方。

### `moods`：当前状态

`(space, subject)` 为主键；`value`（写入时为 0–100）；`emotions`（JSON 对象，情绪 → 强度 0–100）；
`updated_at`；`last_event`（`mood_events` 中的 id）；`told_event`（最后一次告诉模型的事件）。

存储的值以 `updated_at` 为准。要读取时刻 *t* 的状态，设 *h* 为距 `updated_at` 的小时数：

    value(t)   = baseline + (value − baseline) · 0.5^(h / 3)
    emotion(t) = emotion · 0.5^(h · 60 / 90)

基线（70）和两个半衰期都是设置，不属于文件的一部分。

### `mood_events`：时间线

`id`、`space`、`subject`、`at`、`delta`（实际应用的改变量）、`value`（改变之后的值）、`emotions`
（JSON：这个事件新增了什么）、`reason`（推动它的原因，用显示语言写：判断器的句子，或对方原话的引用；
情绪则取自 `emotions` 告诉模型）、`confidence`（0–1）、`source`（`user`、`speak-up`、`duty`、
`manual`…）、`judge`（做出回答的层或各层，即其中置信度先被计入的那一层：`luna`、`luna+prompt`）。

### `relationships`：每个人与伴侣的关系

`(space, subject)` 为主键；`role`（`creator`、`family`、`friend`、`acquaintance`，或宿主程序自定义
的值）；`closeness`（0–100，以 `updated_at` 为准）；`since`（赋予角色的时间）；`updated_at`（亲近度
最后一次写入的时间：赋予角色时，或有来往的一天）。

每个空间至多一个 `creator`。使用内置区间时，亲近度保持在角色对应的范围内：创造者 80–100，家人
60–100，朋友 20–90，认识的人 0–60。要读取时刻 *t* 的亲近度，设 *d* 为距 `updated_at` 的天数：

    closeness(t) = max(min(closeness, floor), closeness − d / 30)     （创造者的不会淡去）

在 `updated_at` 之后的某一天（按伴侣所在时区）有来往，会加 1，最多加到该角色的上限。这些速率、区间
和时区都是设置，不属于文件的一部分。

### `note_terms`：检索词索引

`(space, subject, term, memory_id)` 为主键，并在 `memory_id` 上有一个索引。一条笔记的行正好是它
`memories.terms` 中的各个检索词，每个检索词一行；`terms` 为 null 的笔记没有任何行。把 `terms` 置为
null 的写入方（新的译文、新的键、另一个分词器）会删除这条笔记的行；删除笔记的写入方也会删掉它们；
在复用的 id 下插入笔记的写入方会先删除该 id 下残留的任何行。不使用该索引的读取方可以忽略它，但
写入方必须维护它。

### `recalls`：回忆日志

`id`、`space`、`subject`、`at`、`query`、`chosen`（JSON `[[id, why], …]`）、`skipped`
（JSON `[[id, reason], …]`）。每个对象只保留最新的 200 条。

### `micro_models`：判断层 2

`question`（主键：`name:sha1(type|instructions|labels…|tokenizer version)[:12]`）、`kind`、
`labels`（JSON 列表）、`weights`（JSON `{"bias": [...], "w": {"feature": [...]}, "window": [0/1…]}`）、
`examples`、`updated_at`。特征是检索词的 CRC-32 哈希，掩码到 18 位。不运行微型模型的实现可以忽略
这张表。

### `meta`

`key`、`value`。存放 `schema_version`、`terms_version`、`meaning_texts:<embedder>`、
`meaning_version:<embedder>`、`floor:<embedder>`，以及宿主程序可能设置的 `adopted:…` 标志。

`floor:<embedder>` 是一个 JSON 对象：针对那个向量模型、在这个文件里测量到的结果。`floor` 是相似度
下限，低于它时一条笔记对查询说明不了什么；`version` 是内置的校准集的版本（另一个版本的记录会重新
测量）；`separated` 表示该校准集的相关配对是否明显高于其不相关的配对（若否，`floor` 取默认值）；
`set` 保存校准集的 `floor`、相关配对的下四分位数（`related`）、不相关配对的第 95 百分位数
（`unrelated`）以及其不相关笔记配对相似度的中位数（`background`）；`file` 为 null，或者是最后一次
比较本文件自身笔记时的最高笔记 id（`at`）、比较了多少条（`notes`），以及在数量足够时它们相似度的
中位数（`background`）和由此产生的移动量（`shift`）。

## 导出格式

`Mneme.export_data()` / `mneme-llm export` 写出一个 JSON 对象：

```json
{"mneme_llm": 1, "space": "dafeiyu", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", "gloss": null, …}],
 "profiles": [...], "moods": [...], "mood_events": [...], "relationships": [...]}
```

各行即表行对应的对象，不含 `terms` 和 `folded`。向量、词向量中心、下限和微型模型不会被导出：它们属于
embedder 和分词器，会在使用时重建或重新测量。导入时，记忆 id 会重新编号，`superseded_by` 链接跟随新的
编号；每条笔记都要遵守写笔记的规则（单行、至多 500 个字符，空白折叠；键转为小写，若不符合
`part(.part){0,3}` 或超过 48 个字符则丢弃；未知的种类按 `episode` 读取；重要度限制在 1–5，感受限制在
−1…1，`recalls` 限制为 0 或更大；不是 1970 年到 3000 年之间秒数的时间会被替换（`created_at` 换成当前时间，
其余换成 `created_at`）；非文本的 `source` 会被丢弃；不是对象的行、或缺 text 或 subject 的笔记会被跳过）；
随后，对每个对象，每个键下最新的有效笔记保持有效，其余的都指向它，同一段有效文本出现两次时（按大小写折叠
后比较），保留带键的那一份，否则保留第一份（其余标记为已删除）。心情导入时不带事件链接（时间线单独导入）；
与时间线中已有事件相同的事件不会再次加入。一段关系会替换对方当前的关系，其亲近度保持在角色对应的区间内
（宿主程序没有的角色为 0–100）；单人角色出现第二个持有者（第二个创造者）时会被跳过。

## 检索词

为了与 Python 实现的回忆结果保持一致（分词器版本 `4`），文本会先做规范化：NFKC、Unicode 完整
大小写折叠（其中 `i` + U+0307 读作 `i`，所以土耳其语的 *İ* 能匹配 *i*）、U+2019 读作撇号，
并去掉希伯来语注音符号（U+0591–U+05C7）和阿拉伯语元音符号（U+064B–U+065F、U+0670）。
随后，一个检索词是下面之一：

- 一个单词：由任意字母表的字母、数字和组合符号（Unicode 类别 L、N、M）以及 `_` 组成的一串，
  两个这样的字符之间可以出现撇号；去掉首尾的 `'`、`_` 和 `-`，去掉结尾的 `'s`，剩下的须为
  两个及以上字符，再去掉常见的英语虚词；对 ASCII 单词，去掉复数形式的 `s`/`ies`；
- 在一段中日韩字符中，或在不使用空格书写的文字（泰语、老挝语、高棉语、缅甸语）中，每一对
  相互重叠的相邻字符（去掉 我们、什么 等常见虚词组合），以及每一个单字符（去掉 的、了 等
  常见虚词单字和组合符号）。

每个不同的检索词在每段文本中只计一次。安装并启用 jieba 时，jieba 切出的两个及以上字符的词
会追加到中日韩字符串中（版本 `4+jieba`）。其他实现可能采用不同的分词方式；这只影响一次查询
能找到哪些笔记，从不影响存储的内容。

## 结构 1 内的变更

在这些加入之前写入的文件照旧可以打开；写入进程会补上缺少的部分：

- `memories.gloss`、`memories.terms` 和 `memories.folded`（列），以及基于
  `(space, subject, folded)` 的索引 `memories_folded`；
- `vectors` 和 `meaning_terms`（表），以及 `vectors.taught`（列），还有在 `embedder`
  上 `taught` 为 null 时使用的索引 `vectors_untaught`。在早于 `vectors.taught` 的文件中，
  没有任何向量教过任何内容，但 `meaning_texts` 却表明并非如此，因此第一个读取进程会重置这些
  词向量中心（它们可能含有查询里的词，且无法收回），并从已存的向量重新学习；
- `note_terms`（表）及其索引 `note_terms_memory`，以及基于 `(space, subject, id)` 的索引
  `memories_newest` 和基于 `(space, subject, importance, id)` 的索引 `memories_important`。
  早于检索词索引的文件中，每条笔记的 `terms` 要么为 null 要么不为 null；不为 null 的会在
  首次需要时建立索引（读取进程在使用索引前，会为某个对象下 `terms` 为 null、或有 terms
  却没有对应行的任何有效笔记建立索引）；
- `relationships`（表），以及 `meta` 中的 `floor:<embedder>` 键。缺少这些内容的文件没有
  角色（所有人都按以前的方式计算），下限也尚未测量。
