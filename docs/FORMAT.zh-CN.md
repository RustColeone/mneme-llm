# mneme-llm 文件格式（结构 1）

[English](FORMAT.md) · **简体中文**

mneme-llm 文件就是一个 SQLite 3 数据库。本页内容足以让你用任何语言读写它。Python 包只是其中一种实现；下文所述并不依赖它。

时间为 Unix 秒（浮点数，UTC）。文本为 UTF-8。向量为小端序 float32 数组，长度归一化为 1。`meta.schema_version` 为 `1`：读取方遇到版本高于自身已知版本的文件必须拒绝，也可以迁移较低版本的文件。某一版本内新增的列列在[结构 1 内的变更](#changes-within-schema-1)之下；写入方打开较旧的文件时会补上这些列。

## 表

### `memories`：笔记

| 列 | 类型 | 含义 |
|---|---|---|
| `id` | integer | 主键 |
| `space` | text | 这条记忆属于谁（一个应用或角色） |
| `subject` | text | 笔记是关于谁的 |
| `key` | text, null | 它讲的是什么，小写，`part(.part){0,3}`，最多 48 个字符；绝不是值 |
| `kind` | text | `fact`、`preference`、`episode`、`plan` 或 `reflection` |
| `text` | text | 笔记正文，一行，最多 500 个字符 |
| `importance` | integer | 1（琐碎）… 5（核心：始终在上下文中） |
| `feeling` | real | −1 … 1，对象对此的感受（0：中性或未知） |
| `happened_at` | real | 发生的时间（对于计划：计划发生的那一天） |
| `created_at` | real | 写入的时间 |
| `recalled_at` | real, null | 最后一次被证据回忆的时间 |
| `recalls` | integer | 被回忆的次数 |
| `superseded_by` | integer, null | 取代它的那条笔记的 id（同一个键） |
| `deleted_at` | real, null | 被遗忘的时间 |
| `source` | text, null | 谁写的：`auto`（模型主动写的）、`user`、`cli`、`core-diary`… |
| `gloss` | text, null | 用统一语言写成的该笔记（意思层第 3 层），写了译文时才有 |
| `terms` | text, null | 缓存：该笔记的检索词，以空格分隔；任何时候都可能为 null |
| `folded` | text, null | 缓存：做过 Unicode 完整大小写折叠的 `text`（并把 `i` + U+0307 读作 `i`），用于查重；可能为 null |

当 `superseded_by` 与 `deleted_at` 都为 null 时，笔记是**有效的**。写入一条带键的
笔记时，会给同一个 `(space, subject, key)` 下的有效笔记设置 `superseded_by`，因此每个键
最多只有一条有效笔记。`text` 和 `gloss` 永远不含换行（写入时空白会被折叠）。

`terms` 属于写入它的那个分词器（`meta.terms_version`）；分词器不同的读取方会把所有
`terms` 置为 null，并在使用时重建。改了 `text` 或 `gloss` 的写入方会把 `terms` 置为
null。`folded` 在写入时填好；要比较文本的写入方会先补齐该对象所有为 null 的 `folded`。
同一个对象的两条有效笔记不会有相同的 `folded`，除非两条都有键且键不同。

### `vectors`：意思层第 1 层

`(memory_id, embedder)` 主键；`vector`（blob）；`taught`（text，null：这个向量教给词向量
中心的检索词，以空格分隔，可能为空；没教过任何东西时为 null）。`embedder` 指明模型及其
设置（`openai:text-embedding-3-small:256`）；不同 embedder 的向量从不互相比较。已不存在
的笔记对应的行会在 `purge` 和 `erase` 时删除。

### `meaning_terms`：意思层第 2 层

`(embedder, term)` 主键；`count`（有多少条学过的笔记包含该检索词）；`vector`（blob：那些
笔记向量的滑动均值，未重新归一化）。只学习笔记，从不学习查询。
`meta."meaning_texts:<embedder>"` 记录已学习的笔记数，始终等于该 embedder 的 `taught` 不为
null 的向量数（读取方若发现不符，或发现存在没有任何教学来源的检索词，就重置该 embedder 的
词向量中心），而 `meta."meaning_version:<embedder>"` 记录切分这些检索词的分词器；分词器不同
时这些行不会被使用，下一次学习会先删掉它们。

写入方在学习一条笔记时，会在同一个事务里加入向量行、各检索词新的滑动均值，以及 `taught`
中的检索词；前提是该笔记仍然存在且文本就是被向量化的那段（被删除笔记的 id 会被复用），
并且它还没有该 embedder 的向量。插入笔记的写入方会删掉该 id 下残留的任何向量行。删除笔记
的写入方会先收回该笔记每个向量教过的东西：对 `taught` 中的每个检索词，`count` 减一，均值
变为 `(mean · count − vector) / (count − 1)`，`count` 减到 0 时该行删除；`meaning_texts`
减一。这一步不需要分词器。不运行这一层的实现，在删除笔记时也必须这么做，否则被删笔记的
词会一直留在文件里。重置某个 embedder 的词向量中心会删除它的所有行和两个 meta 键，并把
它的向量的 `taught` 置为 null；这些向量会重新从文件中学习。

### `profiles`：印象卡片

`(space, subject)` 主键，`text`，`updated_at`。几句话，显示在笔记上方。

### `moods`：当前状态

`(space, subject)` 主键；`value`（写入时 0–100）；`emotions`（JSON 对象，情绪 → 强度 0–100）；
`updated_at`；`last_event`（`mood_events` 中的 id）；`told_event`（最后一个告诉模型的事件）。

存储的值是 `updated_at` 时刻的值。要读取时刻 *t* 的状态，设 *h* = 距 `updated_at` 的小时数：

    value(t)   = baseline + (value − baseline) · 0.5^(h / 3)
    emotion(t) = emotion · 0.5^(h · 60 / 90)

基线（70）和两个半衰期都是设置项，不属于文件内容。

### `mood_events`：时间线

`id`、`space`、`subject`、`at`、`delta`（实际应用的改变量）、`value`（改变后的值）、`emotions`
（JSON：该事件新增的部分）、`reason`、`confidence`（0–1）、`source`（`user`、`speak-up`、
`duty`、`manual`…）、`judge`（作答的一层或多层，例如 `luna` 或 `micro+prompt`）。

### `recalls`：回忆日志

`id`、`space`、`subject`、`at`、`query`、`chosen`（JSON `[[id, why], …]`）、`skipped`
（JSON `[[id, reason], …]`）。每个对象保留最新的 200 条。

### `micro_models`：判断层第 2 层

`question`（主键：`name:sha1(type|instructions|labels…|tokenizer version)[:12]`）、`kind`、
`labels`（JSON 列表）、`weights`（JSON `{"bias": [...], "w": {"feature": [...]}, "window": [0/1…]}`）、
`examples`、`updated_at`。特征是检索词的 CRC-32 哈希，掩码到 18 位。不运行微型模型的实现
可以忽略这张表。

### `meta`

`key`、`value`。存放 `schema_version`、`terms_version`、`meaning_texts:<embedder>`、
`meaning_version:<embedder>`，以及宿主程序可能设置的 `adopted:…` 标志。

## 导出格式

`Mneme.export_data()` / `mneme-llm export` 写出一个 JSON 对象：

```json
{"mneme_llm": 1, "space": "dafeiyu", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", "gloss": null, …}],
 "profiles": [...], "moods": [...], "mood_events": [...]}
```

每一行就是表中的一行，以对象形式给出，不含 `terms` 和 `folded`。向量、词向量中心和
微型模型不会被导出：它们属于 embedder 和分词器，使用时重新构建。导入时，记忆的 id
会重新编号，`superseded_by` 链接会跟随新的编号；每条笔记都要遵守写入规则（单行，
最多 500 个字符，空白会被折叠；键转为小写，若它不是最多 48 个字符的
`part(.part){0,3}`，则丢弃；未知的种类按 `episode` 处理；重要度限制在 1–5，感受限制在
−1…1，`recalls` 限制为 0 或更大；不是 1970 年到 3000 年之间秒数的时间会被替换
（`created_at` 用当前时间，其余用 `created_at`）；不是文本的 `source` 会被丢弃；不是
对象的行，或缺少 text 或 subject 的笔记会被跳过）；然后，对每个对象、每个键，最新的
有效笔记保持有效，其余的都指向它；出现两次的有效文本（比较时按大小写折叠）保留带键
的那一份，否则保留第一份（其余的标记为已删除）。心情导入时不带事件链接（时间线单独
导入）；与时间线中已有事件相同的事件不会再次加入。

## 检索词

为了与 Python 实现的回忆（分词器版本 `4`）保持一致，文本会先做规范化：NFKC、Unicode
完全大小写折叠（其中 `i` + U+0307 读作 `i`，所以土耳其语 *İ* 能匹配 *i*）、U+2019 读作
撇号，并去掉希伯来语注音符号（U+0591–U+05C7）和阿拉伯语元音符号（U+064B–U+065F、U+0670）。
一个检索词则是下列之一：

- 单词：由任意字母表的字母、数字、组合符号（Unicode 类别 L、N 和 M）以及 `_` 组成的一串，
  允许在其中两个字符之间出现撇号；去掉首尾的 `'`、`_` 和 `-`，去掉词尾的 `'s`，然后要求
  不少于两个字符，并去掉常见的英语虚词；对 ASCII 单词，还会裁掉复数的 `s`/`ies`；
- 在一串中文、日文或韩文字符中，或在一段不用空格书写的文字（泰语、老挝语、高棉语、缅甸语）
  中，每一对相邻重叠的两个字符（像 我们 和 什么 这样的常见虚词组合会被去掉）以及每一个
  单字符（像 的 和 了 这样的常见虚词字符和组合符号会被去掉）。

每个不同的检索词在每段文本中只计一次。若安装并启用了 jieba，则 jieba 切出的两字及以上词语
会加入 CJK 字符序列（版本 `4+jieba`）。其他实现可能采用不同的分词方式；这只影响一次查询能
命中哪些笔记，绝不会影响存储的内容。

## 结构 1 内部的变更

在这些内容加入之前写出的文件仍照旧打开；写入方会补上缺失的部分：

- `memories.gloss`、`memories.terms` 和 `memories.folded`（列），以及
  `(space, subject, folded)` 上的索引 `memories_folded`；
- `vectors` 和 `meaning_terms`（表），以及 `vectors.taught`（列）和
  `embedder` 上 `taught` 为 null 时的索引 `vectors_untaught`。在早于
  `vectors.taught` 的文件里，没有任何向量教过任何内容，而 `meaning_texts`
  的说法却相反，因此第一个读取方会重置这些词向量中心（它们可能含有查询的词，
  且无法收回），并从已存储的向量重新学习它们。
