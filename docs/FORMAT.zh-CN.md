# mneme-llm 文件格式（结构版本 1）

[English](FORMAT.md) · **简体中文**

mneme-llm 文件就是一个 SQLite 3 数据库。看完这一页，用任何语言都能读写它。Python 包只是其中一种实现，下面的内容都不依赖它。

时间是 Unix 秒（浮点数，UTC）。文本是 UTF-8。向量是小端序的 float32 数组，长度归一化为 1。`meta.schema_version` 是 `1`：
读取方遇到比自己认识的版本更高的文件必须拒绝，遇到更低的可以迁移。同一版本内新增的列见
[结构版本 1 内的变化](#结构版本-1-内的变化)；写入方打开旧文件时会补上。

## 表

### `memories`：笔记

| 列 | 类型 | 含义 |
|---|---|---|
| `id` | integer | 主键 |
| `space` | text | 谁的记忆（一个应用或角色） |
| `subject` | text | 笔记写的是谁 |
| `key` | text，可空 | 关于什么，小写，`part(.part){0,3}`，最多 48 个字符；绝不是值 |
| `kind` | text | `fact`、`preference`、`episode`、`plan` 或 `reflection` |
| `text` | text | 笔记本身，一行，最多 500 个字符 |
| `importance` | integer | 1（无关紧要）… 5（核心：永远带上） |
| `feeling` | real | −1 … 1，对方对这件事的感受（0：中性或未知） |
| `happened_at` | real | 发生的时间（`plan` 是它发生的那天） |
| `created_at` | real | 写下的时间 |
| `recalled_at` | real，可空 | 最近一次按证据被想起的时间 |
| `recalls` | integer | 被想起的次数 |
| `superseded_by` | integer，可空 | 替换它的那条笔记的 id（同一个键） |
| `deleted_at` | real，可空 | 被忘记的时间 |
| `source` | text，可空 | 谁写的：`auto`（模型自己决定的）、`user`、`cli`、`core-diary`…… |
| `gloss` | text，可空 | 笔记用统一语言写的版本（"意思"第三层），写过才有 |
| `terms` | text，可空 | 缓存：这条笔记的检索词，空格分隔；随时可能为空 |

`superseded_by` 和 `deleted_at` 都为空的笔记是**有效**的。写一条带键的笔记时，会给同一个 `(space, subject, key)` 下原来那条有效
笔记设上 `superseded_by`，所以每个键最多只有一条有效笔记。`text` 和 `gloss` 里不会有换行（写入时空白会被合并）。

`terms` 属于写下它的分词器（`meta.terms_version`）；分词器不同的读取方会把所有 `terms` 设为空，用到时再重建。修改了 `text`
或 `gloss` 的写入方要把 `terms` 设为空。

### `vectors`："意思"第一层

主键 `(memory_id, embedder)`；`vector`（二进制）。`embedder` 写明模型和它的设置（`openai:text-embedding-3-small:256`）；不同
embedder 的向量绝不互相比较。笔记不存在了，它的向量会在 `purge` 和 `erase` 时删除。

### `meaning_terms`："意思"第二层

主键 `(embedder, term)`；`count`（含这个词的已嵌入文本数）；`vector`（二进制：这些文本向量的累计平均）。
`meta."meaning_texts:<embedder>"` 记录学过的文本数。不运行这一层的实现可以忽略这张表。

### `profiles`：印象卡片

主键 `(space, subject)`，`text`，`updated_at`。几句话，显示在笔记上方。

### `moods`：当前心情

主键 `(space, subject)`；`value`（写入时 0–100）；`emotions`（JSON 对象，情绪 → 强度 0–100）；`updated_at`；
`last_event`（`mood_events` 里的 id）；`told_event`（最后一次告诉模型的事件）。

存的是 `updated_at` 那一刻的值。要读时刻 *t* 的状态，设 *h* 为距 `updated_at` 的小时数：

    value(t)   = baseline + (value − baseline) · 0.5^(h / 3)
    emotion(t) = emotion · 0.5^(h · 60 / 90)

基线（70）和两个半衰期都是设置，不存在文件里。

### `mood_events`：心情时间线

`id`、`space`、`subject`、`at`、`delta`（实际改变的量）、`value`（改变之后）、`emotions`（JSON：这次加上的情绪）、
`reason`、`confidence`（0–1）、`source`（`user`、`speak-up`、`duty`、`manual`……）、`judge`（回答的那一层或几层，例如
`luna`、`micro+prompt`）。

### `recalls`：回忆记录

`id`、`space`、`subject`、`at`、`query`、`chosen`（JSON `[[id, 原因], …]`）、`skipped`（JSON `[[id, 原因], …]`）。每个对象保留
最新的 200 条。

### `micro_models`："判断"第二层

`question`（主键：`name:sha1(type|instructions|labels…)[:12]`）、`kind`、`labels`（JSON 列表）、`weights`（JSON
`{"bias": [...], "w": {"特征": [...]}, "window": [0/1…]}`）、`examples`、`updated_at`。特征是检索词的 CRC-32 哈希，取低 18 位。
不运行微型模型的实现可以忽略这张表。

### `meta`

`key`、`value`。存 `schema_version`、`terms_version`、`meaning_texts:<embedder>`，以及宿主程序可能写入的 `adopted:…` 标记。

## 导出格式

`Mneme.export_data()` / `mneme-llm export` 写出一个 JSON 对象：

```json
{"mneme_llm": 1, "space": "dafeiyu", "exported_at": 1792885075.5,
 "memories": [{"id": 1, "subject": "discord:42", "key": "pet.name", "kind": "fact", "text": "…", "gloss": null, …}],
 "profiles": [...], "moods": [...], "mood_events": [...]}
```

每行就是表里的一行，去掉 `terms`。向量和微型模型不导出：它们属于某个 embedder 和分词器，用到时会重建。导入时笔记 id 会重新编号，
`superseded_by` 跟着新编号走；心情导入时不带事件链接（时间线单独导入）。

## 检索词

要和 Python 实现的回忆结果一致（分词器版本 `2`），检索词是下面两种之一：

- 拉丁字母的词：NFKC 规范化并转小写，至少两个字符，去掉 `'s` 和复数的 `s`/`ies`，去掉常见虚词；
- 中日韩文字连续的一段里，每两个相邻的字（去掉"我们""什么"这类常见搭配），以及每个单字（去掉"的""了"这类常见虚字）。

装了并启用 jieba 时，再加上 jieba 分出的两个字以上的词（版本 `2+jieba`）。其他实现可以用不同的分词方式；那只会影响一个查询能找到
哪些笔记，不会影响存了什么。

## 结构版本 1 内的变化

在这些加入之前写的文件照常能打开；写入方会补上缺的部分：

- `memories.gloss` 和 `memories.terms`（列）；
- `vectors` 和 `meaning_terms`（表）。
