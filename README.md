# 我的豆瓣 · My Douban

个人影视 / 书 / 音乐标记站。**零依赖**：Python 3.8+ 标准库 + SQLite，不装任何第三方包，断网也能开。

一个更克制的问题：豆瓣把你的「看过 / 想看 / 评分 / 短评」锁在它的服务器里。这个项目把那套机制搬回你自己的机器——条目、五星（半星）、短评长评、想看/在看/看过/弃了、标签、时间线、年度统计，一样不少；只有社交（小组、同城、关注）不做，因为一个人用不上。

## 快速开始

```bash
python app.py                 # 打开 http://127.0.0.1:8601
python app.py --port 9000     # 换端口
python app.py --host 0.0.0.0  # 局域网/手机访问
```

Windows 双击 `start.bat` 也行（会自动开浏览器）。

首次启动自动建库；`data/` 下没有 `douban.db` 时会用 `data/seed.json` 播种 10 条演示条目，方便先看效果。

## 目录

```
app.py                后端 + REST API（单文件，无第三方依赖）
static/index.html     整个前端（原生 JS，无框架、无外链、无 CDN）
data/seed.json        演示数据
data/douban.db        SQLite（运行时生成，不入库）
start.bat             Windows 启动器
```

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查，返回条目数 |
| GET | `/api/schema` | 字段结构（分类 / 状态的可选值） |
| GET | `/api/entries?pageSize=200&startCursor=0` | 列表，按标记日期倒序，游标分页 |
| POST | `/api/entries` | 新增，body `{"properties": {"标题": {"text": "..."}}}` |
| PATCH | `/api/entries/<id>` | **增量**更新，只覆盖传入字段 |
| DELETE | `/api/entries/<id>` | 删除 |

`properties` 沿用 `{字段名: {类型: 值}}` 的形状（`text` / `number` / `select` / `date`），和常见表单序列化习惯一致。

## 数据表

```sql
CREATE TABLE entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, category TEXT, creator TEXT, year INTEGER,
  status TEXT, rating REAL, short_review TEXT, long_review TEXT,
  tags TEXT, marked_date TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
```

## 设计取舍

- **封面不用图床**：按片名做哈希取一组深色渐变，程序化生成海报底图。零外部请求，也永远不会出现图片 404。
- **单文件前端**：CSS / JS / 图标 / 图表（SVG 手写）全内联。双击 HTML 也能看个大概，只是没有数据。
- **不做账号体系**：一个人用，靠 SQLite 文件备份迁移就够了。

## License

MIT，见 `LICENSE`。
