#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""我的豆瓣 · 个人影视 / 书音标记站（零依赖）

技术栈：Python 3.8+ 标准库 + SQLite，不装任何第三方包。
启动：
    python app.py                       # http://127.0.0.1:8601
    python app.py --port 8601 --host 0.0.0.0
数据：
    data/douban.db      SQLite（首次启动自动建表；表为空时用 data/seed.json 播种）
    data/seed.json      演示数据，可随时清空重建

REST 接口（前端只认这四个 + schema/health）：
    GET    /api/health
    GET    /api/schema
    GET    /api/entries?pageSize=200&startCursor=0
    POST   /api/entries            {"properties": {"标题": {"text": "..."}, ...}}
    PATCH  /api/entries/<id>       {"properties": {...}}     增量更新
    DELETE /api/entries/<id>
"""
import argparse
import json
import mimetypes
import os
import re
import sqlite3
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE, "static")
DATA_DIR = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA_DIR, "douban.db")
SEED_PATH = os.path.join(DATA_DIR, "seed.json")

# 中文字段名 -> 数据库列名
COLS = [
    ("标题", "title"),
    ("分类", "category"),
    ("创作者", "creator"),
    ("年份", "year"),
    ("状态", "status"),
    ("评分", "rating"),
    ("短评", "short_review"),
    ("长评", "long_review"),
    ("标签", "tags"),
    ("标记日期", "marked_date"),
]
COL_OF = dict(COLS)
NAME_OF = {v: k for k, v in COLS}
NUMERIC = {"year", "rating"}

CATEGORIES = ["电影", "剧集", "图书", "音乐", "舞台剧", "游戏"]
STATUSES = ["看过", "在看", "想看", "弃了"]

SCHEMA = {
    "properties": [
        {"id": "f_title", "name": "标题", "type": "text"},
        {"id": "f_category", "name": "分类", "type": "select",
         "config": {"options": [{"id": "c_%d" % i, "text": c} for i, c in enumerate(CATEGORIES)]}},
        {"id": "f_creator", "name": "创作者", "type": "text"},
        {"id": "f_year", "name": "年份", "type": "number"},
        {"id": "f_status", "name": "状态", "type": "select",
         "config": {"options": [{"id": "s_%d" % i, "text": s} for i, s in enumerate(STATUSES)]}},
        {"id": "f_rating", "name": "评分", "type": "number"},
        {"id": "f_short", "name": "短评", "type": "text"},
        {"id": "f_long", "name": "长评", "type": "text"},
        {"id": "f_tags", "name": "标签", "type": "text"},
        {"id": "f_date", "name": "标记日期", "type": "date"},
    ]
}


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS entries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            category    TEXT,
            creator     TEXT,
            year        INTEGER,
            status      TEXT,
            rating      REAL,
            short_review TEXT,
            long_review TEXT,
            tags        TEXT,
            marked_date TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_marked ON entries(marked_date DESC, id DESC)")
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    if count == 0 and os.path.exists(SEED_PATH):
        try:
            with open(SEED_PATH, encoding="utf-8") as fh:
                seed = json.load(fh)
        except Exception as exc:                     # 种子坏了不该拖垮服务
            print("[warn] seed.json 读取失败：%s" % exc)
            seed = []
        for rec in seed:
            insert_record(conn, rec, commit=False)
        conn.commit()
        print("[init] 已播种 %d 条演示数据" % len(seed))
    conn.close()


def row_to_dict(row):
    out = {"record_id": str(row["id"])}
    for cn, col in COLS:
        out[cn] = row[col]
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    return out


def coerce_value(cn, raw):
    """把 PropertyValue（{"text": ...}）或裸值转成入库值。"""
    if isinstance(raw, dict):
        if not raw:
            return None
        val = next(iter(raw.values()))
    else:
        val = raw
    if val is None:
        return None
    col = COL_OF.get(cn)
    if col in NUMERIC:
        try:
            num = float(val)
        except (TypeError, ValueError):
            return None
        if col == "year":
            return int(num)
        return num
    if col == "marked_date":
        return str(val)[:10]
    return str(val)


def props_to_row(properties):
    row = {}
    for cn, col in COLS:
        if cn in properties:
            row[col] = coerce_value(cn, properties[cn])
    return row


def insert_record(conn, properties, commit=True):
    row = props_to_row(properties)
    row.setdefault("title", "")
    if not row.get("title"):
        raise ValueError("标题不能为空")
    now = now_iso()
    cols = list(row.keys()) + ["created_at", "updated_at"]
    vals = list(row.values()) + [now, now]
    sql = "INSERT INTO entries (%s) VALUES (%s)" % (
        ", ".join(cols), ", ".join(["?"] * len(cols)))
    cur = conn.execute(sql, vals)
    if commit:
        conn.commit()
    return cur.lastrowid


def update_record(conn, rid, properties):
    row = props_to_row(properties)
    if not row:
        return 0
    row["updated_at"] = now_iso()
    sets = ", ".join("%s = ?" % c for c in row)
    vals = list(row.values()) + [rid]
    cur = conn.execute("UPDATE entries SET %s WHERE id = ?" % sets, vals)
    conn.commit()
    return cur.rowcount


class Handler(BaseHTTPRequestHandler):
    server_version = "MyDouban/1.0"
    protocol_version = "HTTP/1.1"

    # ---------- 底层输出 ----------
    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("请求体不是合法 JSON")

    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def do_OPTIONS(self):
        self._send(204, b"")

    # ---------- 静态文件 ----------
    def _serve_static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        target = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not target.startswith(STATIC_DIR) or not os.path.isfile(target):
            self._send(404, {"error": "not found"})
            return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(target, "rb") as fh:
            body = fh.read()
        self._send(200, body, ctype)

    # ---------- GET ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)

        if path == "/api/health":
            conn = connect()
            count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            conn.close()
            self._send(200, {"ok": True, "site": "我的豆瓣", "count": count, "time": now_iso()})
            return

        if path == "/api/schema":
            self._send(200, SCHEMA)
            return

        if path == "/api/entries":
            try:
                page_size = min(500, max(1, int((qs.get("pageSize") or ["50"])[0])))
                cursor = int((qs.get("startCursor") or ["0"])[0] or 0)
            except ValueError:
                page_size, cursor = 50, 0
            conn = connect()
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            rows = conn.execute(
                """SELECT * FROM entries
                   ORDER BY (marked_date IS NULL), marked_date DESC, id DESC
                   LIMIT ? OFFSET ?""", (page_size, cursor)).fetchall()
            conn.close()
            results = [row_to_dict(r) for r in rows]
            nxt = cursor + len(results)
            self._send(200, {
                "results": results,
                "nextCursor": str(nxt),
                "hasMore": nxt < total,
                "total": total,
            })
            return

        if path.startswith("/api/"):
            self._send(404, {"error": "unknown api"})
            return

        self._serve_static(path)

    # ---------- POST ----------
    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path != "/api/entries":
            self._send(404, {"error": "unknown api"})
            return
        try:
            body = self._json_body()
            props = body.get("properties") or body
            conn = connect()
            rid = insert_record(conn, props)
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (rid,)).fetchone()
            conn.close()
            self._send(200, {"id": str(rid), "record": row_to_dict(row)})
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": "写入失败：%s" % exc})

    # ---------- PATCH ----------
    def do_PATCH(self):
        path = unquote(urlparse(self.path).path)
        m = re.match(r"^/api/entries/(\d+)$", path)
        if not m:
            self._send(404, {"error": "unknown api"})
            return
        rid = int(m.group(1))
        try:
            body = self._json_body()
            props = body.get("properties") or body
            conn = connect()
            changed = update_record(conn, rid, props)
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (rid,)).fetchone()
            conn.close()
            if row is None:
                self._send(404, {"error": "记录不存在"})
                return
            self._send(200, {"id": str(rid), "changed": changed, "record": row_to_dict(row)})
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            self._send(500, {"error": "更新失败：%s" % exc})

    # ---------- DELETE ----------
    def do_DELETE(self):
        path = unquote(urlparse(self.path).path)
        m = re.match(r"^/api/entries/(\d+)$", path)
        if not m:
            self._send(404, {"error": "unknown api"})
            return
        rid = int(m.group(1))
        conn = connect()
        cur = conn.execute("DELETE FROM entries WHERE id = ?", (rid,))
        conn.commit()
        conn.close()
        self._send(200, {"deleted": cur.rowcount})


def main():
    parser = argparse.ArgumentParser(description="我的豆瓣 · 本地站")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DOUBAN_PORT", "8601")))
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    init_db()
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        sys.exit("端口 %d 启动失败：%s（换个端口 --port 试试）" % (args.port, exc))
    print("我的豆瓣 已启动 → http://%s:%d" % (args.host, args.port))
    print("数据库：%s" % DB_PATH)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
