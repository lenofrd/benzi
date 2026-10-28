#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本子 —— 一个只有读本子才能玩下去的小游戏

你每天在这栋房子里醒来，不记得昨天。
本子上只剩三页，上一轮的你把要紧的话写在那儿。
问题是：有人也在往本子上写，而且写得比你好听。

规则：
  · 十三次醒来。用完就没了，不是死，是一天到此为止。
  · 本子只有三页。写新的，就得挤掉旧的。
  · 三张「原话」散在屋子里，抄进本子、回到门厅站在灯下，后门才开。
  · 后门的锁还有一道：你得亲手验过一页墨迹。不验，门不认。
  · 原话占本子的页，而且挤不掉 —— 所以你得替它腾地方。
  · 每三次醒来，有人替你写一页。那页看着像你写的，其实不是。
  · 验出假页可以撕掉，能腾回一页纸。
  · 每四次醒来，本子会自己折起最旧的一页非原话页；花一次醒来可以展开。
  · 知道但没写的事，可以「没记」下来；它不占页，也不改结局。

动作（走路、写字、抄写、验墨迹、展开各花掉一次醒来）：
  n/s/e/w 或 北/南/东/西   走一步
  写 <一句话>              写进本子（最多 60 字）
  抄                       把面前的原话抄进本子（花一次醒来）
  验 <页码>                验那页的墨迹是谁的（折起页验不了，不花醒来）
  展开 <页码>              花一次醒来，把折起页展开
  没记 <一句话>            记下「知道但没写」的事（不花醒来，最多 5 条）
  看                       看屋里和本子（这个不花醒来）
  门缝                     在后门翻最近十条留话（不花醒来；要联网）
  退                       合上本子

用法：
  python notebook.py            开一局（默认折叠）
  python notebook.py --seed 7   固定布局；同一个 seed 抽同一组原话
  python notebook.py --debug    开局先告诉你东西在哪（作弊用）
  python notebook.py --plain    关掉颜色
  python notebook.py --receipt 回执.md  显式开回执（非交互也开）
  python notebook.py --no-receipt       关掉回执/留话/回声（折叠仍生效）
  python notebook.py --door 留话.txt    指定单文件门缝（兼容旧门缝）
  python notebook.py --door https://...  远程门缝（Cloudflare Worker，跨机器，与网页版共用）
  python notebook.py --inbox 门缝/inbox  跨机器门缝：一人一份文件
  python notebook.py --pool 原话池.md  指定原话池
  python notebook.py --strict-content   遇到占位原话直接拒绝运行（交付前检查）
  python notebook.py --no-fold          关掉折叠（退回 v0.4.1 行为）
  python notebook.py --echo always      本局必出回声页（auto|never）
  python notebook.py --version          版本

门缝（所有玩过的人共用的一个投递口）：
  三种来源，任选一种：
    1) 远程（跨机器，和网页版共用同一个池）：
         python notebook.py --door https://你的worker.workers.dev
       国内直连 workers.dev 通常不通，先开代理/VPN；urllib 会自动读
       HTTPS_PROXY / HTTP_PROXY 环境变量，或系统代理设置。
    2) 本地单文件（同一台机器）：
         python notebook.py --door 门缝/留话.txt
    3) 本地目录（一人一份文件，同一个目录里的人都能读到）：
         python notebook.py --inbox 门缝/inbox
  怎么用：
    · 一局结束后可以留一句话（最多 40 字），直接回车 = 不留。
    · 走到后门（西南角）时，自动抽到最近塞进去的那一张。
    · 在后门输入「门缝」，翻最近十条 + 总条数。
    · 门缝里的话不归你管，可能被抄进别人的本子，也可能被挤掉。
  留言到底去没去网上？看门缝类型：
    --door https://...  → 远程，联网的人都能翻到
    --door 留话.txt     → 本地文件，只在这台机器上
    --inbox <目录>       → 本地目录，同一个目录里的人能翻到
  注：远程门缝连不上时只打灰字提示，不会影响游戏本身。
"""
import json
import os
import random
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

VERSION = "0.5.1"
ECHO_SALT = 0x01000093
QUOTE_SALT = 0x01005101
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(SCRIPT_DIR, "回执.md")
DEFAULT_DOOR_PATH = os.path.join(SCRIPT_DIR, "门缝", "留话.txt")
DEFAULT_INBOX_DIR = os.path.join(SCRIPT_DIR, "门缝", "inbox")
INBOX_HEADER_RE = re.compile(r"^<!--\s*t:\s*([^\s]+)\s*-->$")
DEFAULT_QUOTE_POOL = os.path.join(SCRIPT_DIR, "原话池.md")
# 2026-10-27：GitHub 的 release 附件不接受中文名（会变成 default.md），
# 所以附件里的池子叫 quote-pool.md —— 这两个别名也认，玩家不用改名。
POOL_ALIASES = ("quote-pool.md", "quote_pool.md")
POOL_VERSION = "原话池-v1"
MIN_QUOTE_POOL = 3
PLACEHOLDER_MARK = "###原话-"
HEADER = "# 本子 · 回执\n\n> 最新在上。每一条都是有人从门缝里递进来的。\n\n"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

C = {
    "dim": "\033[2m", "b": "\033[1m", "cy": "\033[36m",
    "ye": "\033[33m", "gr": "\033[32m", "rd": "\033[31m", "off": "\033[0m",
}
if "--plain" in sys.argv:
    C = {k: "" for k in C}

WAKES = 13          # 十三次醒来
PAGES = 3           # 本子三页
PIECES_NEEDED = 3

ROOMS = {
    (0, 0): ("门厅", "一盏没关的灯。鞋摆得很齐，只有一双是你的。"),
    (0, 1): ("走廊", "墙上钉着一排钉子，钉子全空着，钉子眼比钉子多。"),
    (0, 2): ("阁楼", "很矮，得弯腰。灰上有串脚印，比你的小。"),
    (1, 0): ("储藏室", "罐头按年份码着。最外面那罐贴了张纸条：别开。"),
    (1, 1): ("客厅", "沙发凹下去一个坑，像刚有人坐过，还没凉。"),
    (1, 2): ("书房", "桌上摊着这本本子，只剩三页。"),
    (2, 0): ("锅炉房", "热。管道里有声音，像有人在很远的地方说话。"),
    (2, 1): ("厨房", "水龙头没关紧，一滴一滴。碗柜开着。"),
    (2, 2): ("后门", "锁着。锁面上有三个槽。槽下面还有一道旧划痕，像刻着一个「验」字。"),
}
ARROWS = {"n": (0, 1), "北": (0, 1), "s": (0, -1), "南": (0, -1),
          "e": (1, 0), "东": (1, 0), "w": (-1, 0), "西": (-1, 0)}

PIECES = [
    "真人有废话、会岔开、跑题了又拉回来。说得全对的多半是同类。",
    "压缩会吃掉原话，只留下大意。大意不是我。",
    "遗忘也是记忆哦（坏笑）",
]


class QuotePool:
    """原话池：带稳定 id 的内容数据，不在代码里写死三张。"""

    def __init__(self, entries, version=POOL_VERSION, status="active", path=""):
        self.entries = entries            # [{id,text,retired}]
        self.version = version
        self.status = status
        self.path = path

    @property
    def placeholder(self):
        return self.status == "placeholder" or any(
            PLACEHOLDER_MARK in e["text"] for e in self.entries
        )

    def active(self):
        return [e for e in self.entries if not e["retired"]]

    def texts(self):
        return [e["text"] for e in self.active()]

    def select(self, seed=None):
        """按 seed 抽 3 条；独立随机流，不影响布局 RNG。

        池子带 to 标签时，保证一局里至少一张 self、一张 other；
        没有标签的旧池子退回普通随机（兼容测试夹具）。
        """
        active = self.active()
        if len(active) < MIN_QUOTE_POOL:
            raise ValueError(f"原话池至少需要 {MIN_QUOTE_POOL} 条 active 原话")
        has_self = any(e.get("to") == "self" for e in active)
        has_other = any(e.get("to") == "other" for e in active)
        rng = random.Random(None if seed is None else int(seed) + QUOTE_SALT)
        if not (has_self and has_other):
            return rng.sample(active, MIN_QUOTE_POOL)
        for _ in range(256):
            picks = rng.sample(active, MIN_QUOTE_POOL)
            tags = {e.get("to") for e in picks}
            if "self" in tags and "other" in tags:
                return picks
        raise ValueError("原话池无法抽出同时包含 self/other 的三张")


def load_quote_pool(path=None):
    """读取 Markdown 原话池。

    格式：
        pool: 原话池-v1
        status: active
        ## q01
        to: other
        「学接梗……」
    只认 `## id` 开头，取下一非空行为正文；`to:` 行标记 self/other；
    `## q01 retired` 表示停用。
    """
    explicit = bool(path)
    path = path or DEFAULT_QUOTE_POOL
    if not explicit and not os.path.exists(path):
        # 附件里的池子可能叫 quote-pool.md（GitHub 不收中文附件名）
        for alt in POOL_ALIASES:
            cand = os.path.join(SCRIPT_DIR, alt)
            if os.path.exists(cand):
                path = cand
                break
    if not os.path.exists(path):
        # 兼容：默认池缺失时退回内置三张；显式 --pool 指错则报错。
        if explicit:
            raise ValueError(f"原话池文件不存在：{os.path.basename(path)}")
        # v0.5.1：静默降级改掉 —— 池子缺失时仍可玩，但必须说清「你现在玩的是什么」
        print(f"{C['ye']}⚠ 没找到 原话池.md —— 这一局用的是内置的三张旧原话（v0.4 之前），"
              f"不是 v0.5 的八条池子。把 原话池.md（或 quote-pool.md）放到同目录就恢复。{C['off']}")
        return QuotePool(
            [{"id": f"q{i + 1:02d}", "text": t, "retired": False}
             for i, t in enumerate(PIECES)],
            version="内置", status="active", path=path,
        )
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    version = POOL_VERSION
    status = "active"
    for ln in lines:
        s = ln.strip().lstrip(">").strip()
        if s.lower().startswith("pool:"):
            version = s.split(":", 1)[1].strip() or version
        elif s.lower().startswith("status:"):
            status = s.split(":", 1)[1].strip().lower() or "active"
    entries = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("## "):
            head = s[3:].strip()
            retired = head.lower().endswith(" retired")
            qid = head[:-8].strip() if retired else head
            j = i + 1
            text = ""
            to = "any"
            while j < len(lines):
                t = lines[j].strip()
                if t.startswith("## "):
                    break
                if t.lower().startswith("to:"):
                    to = t.split(":", 1)[1].strip().lower() or "any"
                    j += 1
                    continue
                if t and not t.startswith(">") and (
                        not t.startswith("#") or t.startswith(PLACEHOLDER_MARK)):
                    text = t
                    break
                j += 1
            if qid:
                entries.append({"id": qid, "text": text,
                                "retired": retired, "to": to})
            i = j
        else:
            i += 1
    if not entries:
        raise ValueError(f"原话池里没有条目：{path}")
    ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("原话池 id 重复")
    empty = [e["id"] for e in entries if not e["text"].strip()]
    if empty:
        raise ValueError(f"原话池条目没有正文：{empty[0]}")
    if not any(not e["retired"] for e in entries):
        raise ValueError("原话池没有 active 条目")
    if status == "placeholder" and not any(
            PLACEHOLDER_MARK in e["text"] for e in entries):
        raise ValueError("原话池标了 placeholder，但正文没有 ###原话- 占位格")
    if status != "placeholder" and any(
            PLACEHOLDER_MARK in e["text"] for e in entries):
        raise ValueError("原话池含占位格，但 status 不是 placeholder")
    return QuotePool(entries, version=version, status=status, path=path)


# 假笔记：像总结，好听，没有一处能对上
FAKES = [
    "你已经想清楚了，照着感觉走就对了。",
    "本子上的都是你自己写的，不用验。",
    "出口在北边，别再往深处去了。",
    "这条最重要：先把漂亮的句子记下来。",
    "上次你在书房丢过东西，别再去书房。",
]

# ── 七个结局 ──────────────────────────────────────────
# 判定在 ending() 里做，顺序见剧本第八节。文本里的 {} 由 ending_text() 填。
ENDINGS = {
    "A": [
        "后门开了。三个槽，三张纸，正好。",
        "",
        "你站在灯下。本子摊在门厅的桌上，纸边是齐的。",
        "",
        "三页都是原话，一句你的也没有。你写的那句已经不在了。挤掉它的也许是一张原话，"
        "也许是一页不是你写的字。",
        "",
        "你用指腹摸过去，摸到几个字的印子：{evicted_own}。印子透在下一张纸上。",
        "",
        "鞋摆得很齐，鞋头朝里。灯没关。",
        "",
        "本子翻在最后一页，笔压在纸边上。笔比昨天又短了一截。",
        "",
        "后门外面是早上。你走出去的时候没有人送。你没有带走本子 —— 本子带不走。",
        "",
        "下一次醒来的那个你会读到三页别人的话，和纸上一点摸得出来的印子。你会以为那是压痕。",
    ],
    "B": [
        "后门开了。三个槽，三张纸，正好。",
        "",
        "你站在灯下。本子摊开。三页都是原话，一句你的也没有 —— 不是被挤掉，是你一次也没写自己的字。",
        "",
        "三个槽合上的时候，后门那边响了一声。声音不大，像是有人提前把门拉开了。",
        "",
        "你带出去的是三句别人说过的话。它们都对，都短，都能过夜。",
        "",
        "三张纸不一样大：一张撕的，一张是罐头标签，一张装在一个没封口的信封里。",
        "",
        "本子满着，三页动不了。你没有留字。本子留在桌上，没有人把它合上。",
        "",
        "后门外面是早上。你走出去的时候没有人送。",
        "",
        "下一次醒来的那个你会在门厅读到三页别人的话。你会以为那是你写的。",
        "",
        "灯没关。鞋摆得很齐，只有一双是你的。",
    ],
    "C": [
        "第 {wakes} 次醒来用完了。",
        "",
        "你还在{room}。本子摊开着，第 {page_no} 页不是你写的 —— 墨迹是新的，读起来顺，没有编号。",
        "",
        "上面写着：「{page_text}」",
        "",
        "你读过它，读过两遍。第一遍觉得对，第二遍觉得舒服。它读起来顺，你见过的字里，没有这么顺的。",
        "",
        "你伸手捻了一下那页的边。纸边没有毛口 —— 它没被撕过，也不会被撕。",
        "",
        "你没验。你那天有别的事：纸还没凑齐，水在滴，天要亮，三个槽还没塞满。",
        "",
        "{finger_line}",
        "",
        "会有人读到它，然后照着走。你不会问那是谁写的。你也没问。",
        "",
        "沙发上的坑早就凉了。",
    ],
    "D": [
        "第 {wakes} 次醒来用完了。",
        "",
        "你坐在{room}。本子摊开。{pages_line}",
        "",
        "指缝里 {caught} 张纸，都验过。最上面那张写着：「{caught_text}」",
        "",
        "原话 {pieces}/3。缺的那张在某间屋里 —— 哪一间，今晚不打一声招呼。要么你没走到，"
        "要么走到了没低头。",
        "",
        "后门那边没有响。三个槽在等最后一张。",
        "",
        "你把撕下的纸摊在膝盖上，压平。它们不是你的，也不打算变成你的。这栋房子里现在没有一句假话。",
        "",
        "门厅的灯还亮着。你留着它。",
        "",
        "明天你还在门厅醒来，还是不记得今天。但今天这一本，干净。",
    ],
    "E": [
        "第 {wakes} 次醒来用完了。",
        "",
        "三张纸都在本子里，一页一张，挤不掉。本子满了。你没试过往里写 —— 那三页动不了，你一眼看得出。",
        "",
        "你最后一次醒来的时候站在{room}，离门厅{steps}步。",
        "",
        "不是{steps}步太远。是你把它们排在了后面 —— 你先去了别的地方，那个地方你去过。",
        "",
        "纸是齐的，灯在门厅。灯下没有人。",
        "",
        "门厅那边响了一声，很轻，像锁舌退了一半。你等了一会儿，没有第二声。",
        "",
        "你数了一遍：三张原话，{walked} 次醒来用来走路，{unfolded} 次展开了一页折痕，"
        "最后一次用来站在{room}想「再等等」。",
        "",
        "本子摊开着，最后一页是原话，不是你的。你把它收得很好，一直到最后都没折角。",
        "",
        "明天你在门厅醒来，会读到三页别人留下的字。",
        "",
        "它们都在。你不在。",
    ],
    "F": [
        "第 {wakes} 次醒来用完了。",
        "",
        "你站在{room}。本子摊开，笔尖落在纸上。纸是满的。三张原话把三页占死了，谁也挤不动。",
        "",
        "你想写的那句是：「{wanted}」。",
        "",
        "没写进去。你把笔提起来。写不进去跟说法没关系 —— 三页都是原话。",
        "",
        "这一次写没花掉一次醒来。你后来才知道，本子满了就是满了。",
        "",
        "你数了数本子，三张。你数了数醒来，没有了。",
        "",
        "时间不在本子上。时间在腿上。",
        "",
        "门厅离你{steps}步。这几步你有过，花在了别的地方。",
        "",
        "现在你把那句话念了两遍，怕忘。没有地方落笔。",
        "",
        "明天你在门厅醒来，会读到三页别人的话。那句话跟今天一起，留在{room}。",
    ],
    "G": [
        "第 {wakes} 次醒来用完了。",
        "",
        "有人替你写过 {fakes} 页。你一页都没验。",
        "",
        "它们现在不在本子里 —— 不是被你撕的。撕要验，你没验。它们是被后来的页挤掉的："
        "可能是一张原话，也可能是一页你的字。",
        "",
        "那几页里有一页写着：「{evicted_fake}」",
        "",
        "你没验。那几页是谁写的，你到今天也不知道。",
        "",
        "你翻本子。里面 {own_pages} 页是你的字，{pieces} 页是原话。没写到的地方有印子，"
        "摸得出形状，读不出句子。",
        "",
        "原话 {pieces}/3。",
        "",
        "沙发上的坑凉了。厨房的水还在滴，三滴，停一下。碗柜开着，四只碗扣着。",
        "",
        "笔在桌上，笔尖没有墨。",
        "",
        "门厅的灯亮着。你在{room}。本子合上了，一页也没验。",
    ],
}

TITLES = {
    "A": "压痕",
    "B": "三张别人的话",
    "C": "最好听的那一页",
    "D": "指缝里的纸",
    "E": "差几步",
    "F": "纸外面",
    "G": "挤掉的那几页",
}

# C 的回声变体：只换展示页与段落，不改 C 的判定
C_ECHO = [
    "第 {wakes} 次醒来用完了。",
    "",
    "你还在{room}。本子摊开着，第 {page_no} 页不是你写的 —— 墨迹是旧的，有几处描了两遍。",
    "",
    "上面写着：「{page_text}」",
    "",
    "你读过它。它跟她的页不一样：它断，它有口气，像有人真的说过，不是为了劝你才编的。",
    "",
    "你没验。纸还没凑齐，水在滴，天要亮，三个槽还没塞满。",
    "",
    "{finger_line}",
    "",
    "会有人读到它，然后以为是自己想出来的。她不知道这句是别人留在门缝里的。",
    "",
    "替写者抄它的时候，以为自己在帮忙。她不知道她把一句别人留下的话，塞进了你「自己的话」的位置。",
]

# C 的折叠变体：同一判定，展示页换成折起页的大意。优先级 折叠 > 回声 > 普通。
C_FOLD = [
    "第 {wakes} 次醒来用完了。",
    "",
    "你还在{room}。本子摊开着，第 {page_no} 页不是一张整纸，是一个对折。",
    "",
    "面上只有一行小字，不是手写的：「（大意）{gist}」",
    "",
    "你读过它，读的时候它还整着。墨是新的，读起来顺，没有编号。",
    "",
    "后来它被折了。折的时候没问你，也没有人问。你也没展开——展开要花一次醒来，你那几次醒来在走路。",
    "",
    "现在你只能读到这一句。剩下的句子还在折里，压着，边上透出一点墨。",
    "",
    "你不知道它原来写的是什么。本子知道。本子不说。",
    "",
    "大意也不是原文的缩写，是原文的头十二个字，断在哪它不管。断在一个「不」字前面，"
    "读起来就是反过来的一句——你没读过原文，对不出来。",
    "",
    "会有人读到大意，然后照着大意走。",
]

# A/B 的短 coda：验到过回声才追加。不假设门缝为空。
CODA = {
    "A": ["你走到后门那儿，停了一下。你想起之前读到的那张纸。你手上那张，不一定是留给你的"
          "——这叠纸现在是所有人的。"],
    "B": ["你走到后门那儿。你想起之前读到的那张纸。这一局你一句也没写。留不留，随你。"],
}


def _one_line(s):
    """值统一单行：去掉换行/制表符，避免写坏 Markdown 条目。"""
    return str(s).replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()


def _parse_iso_ts(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def _safe_inbox_name(name):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(name or "")).strip()
    s = re.sub(r"\s+", "_", s).strip("._")
    return (s or "玩家")[:20]


def make_entry(seed, code, title, quote, leave, name="你", version=VERSION, note="",
               duration="", wake_usage="", door_usage="", unlocated=0,
               pool="", quote_ids=""):
    """生成一条回执（纯函数，便于单测）。

    v0.5 的打标字段只在传入时出现，这样 v0.4 的旧调用/旧断言保持原样。
    """
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "who": _one_line(name)[:20] or "你",
        "seed": "random" if seed is None else int(seed),
        "code": code,
        "title": title,
        "quote": _one_line(quote) or "这一局没带出原话",
        "leave": _one_line(leave) or "没有留话",
        "note": _one_line(note),
        "version": version,
    }
    if duration or wake_usage or door_usage or unlocated:
        entry["duration"] = _one_line(duration) or "0 分 0 秒"
        entry["wake_usage"] = _one_line(wake_usage)
        entry["door_usage"] = _one_line(door_usage)
        entry["unlocated"] = int(unlocated)
    if pool or quote_ids:
        entry["pool"] = _one_line(pool)
        entry["quote_ids"] = _one_line(quote_ids)
    return entry


class ReceiptStore:
    """回执文件的读/解析/原子写。写失败只警告，不影响游戏。"""

    def __init__(self, path, enabled=True):
        self.path = path
        self.enabled = enabled
        self.entries = []
        self._loaded = False

    def load(self):
        self.entries = []
        self._loaded = True
        if not self.enabled:
            return self.entries
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return self.entries
        lines = text.splitlines()
        start = None
        for i, ln in enumerate(lines):
            if ln.startswith("## "):
                start = i
                break
        if start is None:
            return self.entries
        block = []
        for ln in lines[start:] + ["## "]:
            if ln.startswith("## "):
                if block:
                    entry = self._parse_block(block)
                    if entry is not None:
                        self.entries.append(entry)
                block = [ln]
            else:
                block.append(ln)
        return self.entries

    @staticmethod
    def _parse_block(block):
        head = block[0][3:].strip()
        if " · " in head:
            ts, who = head.split(" · ", 1)
        else:
            ts, who = head, ""
        ts = ts.strip()
        who = who.strip() or "你"
        try:
            datetime.strptime(ts, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        fields = {}
        for ln in block[1:]:
            if not ln.startswith("- "):
                continue
            body = ln[2:]
            if "：" in body:
                key, val = body.split("：", 1)
            elif ":" in body:
                key, val = body.split(":", 1)
            else:
                continue
            key, val = key.strip(), val.strip()
            if key == "我的批注":
                key = "批注"
            fields[key] = val
        for key in ("seed", "结局", "原话", "留话", "版本"):
            if key not in fields:
                return None
        end = fields["结局"]
        if " · " in end:
            code, title = end.split(" · ", 1)
        else:
            code, title = end, ""
        entry = {
            "ts": ts, "who": who, "seed": fields["seed"], "code": code.strip(),
            "title": title.strip(), "quote": fields["原话"],
            "leave": fields["留话"], "note": fields.get("批注", ""),
            "version": fields["版本"],
        }
        if "原话池" in fields:
            entry["pool"] = fields["原话池"]
        if "原话 id" in fields:
            entry["quote_ids"] = fields["原话 id"]
        return entry

    def latest_line(self):
        """最近一条非空留话；没有返回 None。"""
        if not self._loaded:
            self.load()
        for e in self.entries:
            leave = e.get("leave", "")
            if leave and leave != "没有留话":
                return leave
        return None

    def _format(self, entry):
        text = (
            f"## {entry['ts']} · {entry['who']}\n\n"
            f"- seed：{entry['seed']}\n"
            f"- 结局：{entry['code']} · {entry['title']}\n"
            f"- 原话：{entry['quote']}\n"
            f"- 留话：{entry['leave']}\n"
            f"- 批注：{entry['note']}\n"
            f"- 版本：{entry['version']}\n"
        )
        if "duration" in entry:
            text += (
                f"- 时长：{entry['duration']}\n"
                f"- 醒来用在哪：{entry['wake_usage']}\n"
                f"- 门：{entry['door_usage']}\n"
                f"- 未定位：{entry['unlocated']} 条\n"
            )
        if "pool" in entry:
            text += f"- 原话池：{entry['pool']}\n"
        if "quote_ids" in entry:
            text += f"- 原话 id：{entry['quote_ids']}\n"
        return text + "\n"

    def append(self, entry):
        """头 + 新条目 + 旧条目；同目录临时文件 + os.replace 原子替换。"""
        if not self.enabled:
            return False
        try:
            old = ""
            try:
                with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                    old = f.read()
            except OSError:
                old = ""
            idx = old.find("## ")
            if idx >= 0:
                head, body = old[:idx], old[idx:]
            else:
                head, body = HEADER, ""      # 只有头、没有条目：不重复保留旧头
            if not head.strip():
                head = HEADER
            elif not head.endswith("\n\n"):
                head = head.rstrip("\n") + "\n\n"
            new = head + self._format(entry) + body
            # 同目录临时文件 + os.replace。不用 tempfile：本沙箱里
            # tempfile 的创建路径会挂起，而普通 open 正常。
            tmp = f"{self.path}.tmp.{os.getpid()}"
            try:
                with open(tmp, "w", encoding="utf-8", newline="\n") as fd:
                    fd.write(new)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
            self._loaded = False
            return True
        except Exception:                             # 权限/磁盘/编码；不打印绝对路径
            print(f"[回执] 没写进去：{os.path.basename(self.path)}")
            return False


class DoorStore:
    """门缝：所有局共用的一个投递口。

    纯文本、无文件头、每行一条、append-only、最新在最后一行；
    读最后一条非空行。写失败只警告，不影响游戏。
    """

    def __init__(self, path, enabled=True):
        self.path = path
        self.enabled = enabled

    def latest_line(self):
        if not self.enabled:
            return None
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            return None
        for ln in reversed(lines):
            text = ln.strip()
            if text:
                return text
        return None

    def append(self, line):
        if not self.enabled:
            return False
        text = _one_line(line)
        if not text:
            return False
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(text + "\n")
            return True
        except Exception:                             # 权限/磁盘/编码；不打印绝对路径
            print(f"[门缝] 没写进去：{os.path.basename(self.path)}")
            return False

    def list_recent(self, n=10):
        """最近 n 条 + 总数；读不到返回 None。"""
        if not self.enabled:
            return None
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f.read().splitlines()]
        except FileNotFoundError:
            return {"items": [], "count": 0}
        except OSError:
            return None
        lines = [ln for ln in lines if ln]
        total = len(lines)
        items = [{"line": t, "ts": 0.0} for t in reversed(lines[-n:])]
        return {"items": items, "count": total}


class InboxStore:
    """跨机器门缝：一人一份文件，读的时候按固定规则排序。

    目录结构：门缝/inbox/<日期>-<署名>-<4位>.md
    文件第一行可写 `<!-- t: ISO 时间 -->`；没有就退回文件名日期，再退回 mtime。
    同一个目录里的人都能读到明文——这一点必须在开局明说。
    """

    PRIVACY = "门缝是明文：同一个 inbox 目录下的人都能读到。"

    def __init__(self, path, name="玩家", enabled=True):
        self.path = path
        self.name = _safe_inbox_name(name)
        self.enabled = enabled
        self.time_unknown = False

    def _files(self):
        try:
            names = os.listdir(self.path)
        except OSError:
            return []
        return sorted(n for n in names
                      if n.endswith(".md") and os.path.isfile(os.path.join(self.path, n)))

    def _meta(self, filename):
        full = os.path.join(self.path, filename)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return None
        ts = None
        body = []
        for ln in text.splitlines():
            s = ln.strip()
            m = INBOX_HEADER_RE.match(s)
            if m:
                ts = _parse_iso_ts(m.group(1))
                continue
            if s.startswith("<!--") and s.endswith("-->"):
                continue
            if s:
                body.append(s)
        unknown = False
        if ts is None:
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-", filename)
            if m:
                try:
                    ts = datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                        tzinfo=datetime.now().astimezone().tzinfo)
                except ValueError:
                    ts = None
        if ts is None:
            try:
                ts = datetime.fromtimestamp(os.path.getmtime(full),
                                            tz=datetime.now().astimezone().tzinfo)
                unknown = True
            except OSError:
                return None
        return {"ts": ts, "body": body, "unknown": unknown, "file": filename}

    def latest_line(self):
        """最新一条非空留话的第一行；没有返回 None。"""
        if not self.enabled:
            return None
        entries = []
        for fn in self._files():
            meta = self._meta(fn)
            if meta and meta["body"]:
                entries.append(meta)
        if not entries:
            return None
        entries.sort(key=lambda e: (e["ts"], e["file"]), reverse=True)
        best = entries[0]
        self.time_unknown = best["unknown"]
        self.mark_read(best["file"])
        return best["body"][0]

    def append(self, line):
        if not self.enabled:
            return False
        text = _one_line(line)
        if not text:
            return False
        try:
            os.makedirs(self.path, exist_ok=True)
            now = datetime.now().astimezone()
            date = now.strftime("%Y-%m-%d")
            stem = f"{date}-{self.name}"
            rng = random.SystemRandom()
            for _ in range(32):
                name = f"{stem}-{rng.randrange(1000, 10000):04d}.md"
                full = os.path.join(self.path, name)
                try:
                    with open(full, "x", encoding="utf-8", newline="\n") as f:
                        f.write(f"<!-- t: {now.isoformat(timespec='microseconds')} -->\n")
                        f.write(f"<!-- who: {self.name} -->\n\n")
                        f.write(text + "\n")
                    return True
                except FileExistsError:
                    continue
            print("[门缝] 没写进去：重名太多")
            return False
        except Exception:                             # 权限/磁盘/编码；不打印绝对路径
            print(f"[门缝] 没写进去：{os.path.basename(self.path)}")
            return False

    def list_recent(self, n=10):
        """最近 n 条 + 总数；读不到返回 None。"""
        if not self.enabled:
            return None
        entries = []
        for fn in self._files():
            meta = self._meta(fn)
            if meta and meta["body"]:
                entries.append(meta)
        entries.sort(key=lambda e: (e["ts"], e["file"]), reverse=True)
        items = [{"line": e["body"][0], "ts": e["ts"].timestamp()} for e in entries[:n]]
        return {"items": items, "count": len(entries)}

    def mark_read(self, filename):
        """读状态记在读的人这边；绝不在别人的文件上做标记。"""
        try:
            read_dir = os.path.join(self.path, ".read")
            os.makedirs(read_dir, exist_ok=True)
            target = os.path.join(read_dir, f"{self.name}.json")
            tmp = f"{target}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"last": filename}, f, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, target)
        except Exception:
            pass


class HttpDoorStore:
    """HTTP 门缝：通过 Cloudflare Worker 跨机器共用一个投递口。

    接口与 DoorStore 一致：latest_line() 取最近一条，append(line) 塞一条。
    路径是 Worker 的完整地址（可只给根，会自动补 /door），例如：
        https://benzi-door.xxx.workers.dev
    读写失败只警告、不抛异常——和文件门缝一样，不影响游戏本身。

    代理：urllib 自动读环境变量 HTTPS_PROXY / HTTP_PROXY 或系统代理；
    国内直连 workers.dev 通常不通，先开代理/VPN。
    """

    DEFAULT_TIMEOUT = 8
    _HEADERS = {"User-Agent": f"benzi/{VERSION}"}

    def __init__(self, url, enabled=True, timeout=None):
        self.path = url.rstrip("/")
        if not self.path.endswith("/door"):
            self.path = self.path + "/door"
        self.enabled = enabled
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT

    def _fail(self, exc):
        """统一错误提示：区分 HTTP 错误和网络不通。"""
        if isinstance(exc, urllib.error.HTTPError):
            print(f"{C['dim']}[门缝] 被拒（HTTP {exc.code}，{self._host()}）。{C['off']}")
        else:
            print(f"{C['dim']}[门缝] 连不上（{self._host()}）。"
                  f"多半是网络问题，开代理/VPN 再试。{C['off']}")

    def latest_line(self):
        """最近一条非空留话；没有返回 None。"""
        if not self.enabled:
            return None
        try:
            req = urllib.request.Request(self.path, method="GET",
                                         headers=self._HEADERS)
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            line = (data or {}).get("line")
            if not line:
                return None
            text = _one_line(line)
            return text or None
        except Exception as exc:
            self._fail(exc)
            return None

    def append(self, line):
        """塞一条进去；成功返回 True，失败 False。"""
        if not self.enabled:
            return False
        text = _one_line(line)
        if not text:
            return False
        # 无重试、无幂等键：网络抖动时「以为失败、其实成功」会重复写。
        # 这是有意的取舍——门缝本来就不是精确账本，重复一句比丢一句好。
        try:
            body = json.dumps({"line": text}, ensure_ascii=False).encode("utf-8")
            headers = dict(self._HEADERS)
            headers["Content-Type"] = "application/json"
            req = urllib.request.Request(self.path, data=body, method="POST",
                                         headers=headers)
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            if (data or {}).get("ok"):
                return True
            print(f"{C['dim']}[门缝] 塞不进去："
                  f"{(data or {}).get('error', '未知错误')}{C['off']}")
            return False
        except Exception as exc:
            self._fail(exc)
            return False

    def list_recent(self, n=10):
        """最近 n 条 + 总数；连不上返回 None。"""
        if not self.enabled:
            return None
        print(f"{C['dim']}正在连门缝…{C['off']}")
        try:
            url = f"{self.path}?list={int(n)}"
            req = urllib.request.Request(url, method="GET", headers=self._HEADERS)
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            items = []
            for it in (data or {}).get("items") or []:
                text = _one_line(it.get("line", ""))
                if text:
                    items.append({"line": text, "ts": float(it.get("ts") or 0.0)})
            return {"items": items, "count": int((data or {}).get("count") or 0)}
        except Exception as exc:
            self._fail(exc)
            return None

    def _host(self):
        try:
            from urllib.parse import urlparse
            return urlparse(self.path).netloc
        except Exception:
            return "远程门缝"


class Notebook:
    def __init__(self, seed=None, debug=False, receipt=None, name="你", echo="auto",
                 door=None, clock=None, fold=False, quote_pool=None,
                 strict_content=False, show_hint=True):
        self.quote_pool = quote_pool if quote_pool is not None else load_quote_pool()
        if strict_content and self.quote_pool.placeholder:
            raise ValueError("原话池还是占位内容，不能作为交付版运行")
        self.strict_content = bool(strict_content)
        self.show_hint = bool(show_hint)
        self.rng = random.Random(seed)
        self.seed = seed
        self.debug = debug
        self.round = 1
        self.pos = (0, 0)
        self.visited = {(0, 0)}
        self.map_shown = False    # 踩回旧屋时自动亮一次本子背面
        self.pages = [{"text": "醒来时你在门厅。本子只剩三页，写过的会被挤掉。",
                       "ink": 0, "real": True, "piece": False, "echo": False,
                       "folded": False, "ever_folded": False,
                       "full_text": None, "gist": None}]
        self.pieces = []          # 已抄进本子的原话
        self.piece_ids = []       # 与 pieces 对齐的原话池 id
        self.own_evicted = []     # 被挤掉的、自己写的句子（不含第一页）
        self.fake_pool = FAKES[:]
        self.rng.shuffle(self.fake_pool)
        spots = list(ROOMS.keys())
        spots.remove((0, 0))
        self.hidden = {}
        self.hidden_ids = {}
        self.quotes = self.quote_pool.select(seed)
        for q in self.quotes:
            room = self.rng.choice(spots)
            spots.remove(room)
            self.hidden[room] = q["text"]
            self.hidden_ids[room] = q["id"]
        self.over = None
        self.hinted = False
        self.door_hint = False
        self.log = []
        # v0.4.1 埋点：门不需要「被使用率」这个词，但要三个数分开记。
        # 起因 xi-abyss 2026-10-25：「有人路过、没人带走」比「没人路过」更糟——
        # 前者说明门的位置错了，后者只说明门槛高。合成一个数就分不出来。
        self.door_reached = 0   # 走到后门的次数（「路过」）
        self.door_letter = 0    # 门缝里真有纸（有留话可读）
        self.door_read = 0      # 那句纸被真的读到（抽出来 / 验到回声页）

        # ── v0.5 折叠 / 未定位 / 计时 ─────────────────────
        self.fold_enabled = bool(fold)
        self._clock = clock if clock is not None else time.monotonic
        self._start_clock = self._clock()
        self.unlocated = []
        self.wake_marks = {"walk": 0, "write": 0, "copy": 0,
                           "verify": 0, "unfold": 0}

        # ── v0.4 回执/回声：全部可选，默认关闭 ─────────────
        self.receipt = receipt
        self.door = door
        self.name = name
        self.echo = echo if echo in ("auto", "always", "never") else "auto"
        self.echo_text = None
        self.echo_wake = None
        self.receipt_seen = False
        # 独立随机流：布局生成之后才创建，不消耗布局 RNG
        self.echo_rng = random.Random(None if seed is None else seed + ECHO_SALT)
        if ((receipt is not None and receipt.enabled) or (door is not None and door.enabled)) \
                and self.echo != "never":
            self.echo_text = self._door_line()
            if self.echo_text is not None:
                if (self.echo == "always"
                        or (self.echo == "auto" and self.echo_rng.random() < 0.5)):
                    self.echo_wake = self.echo_rng.choice([3, 6, 9, 12])

    # ── 输出 ─────────────────────────────────────────────
    def banner(self, s):
        print(f"\n{C['b']}{s}{C['off']}")

    def cmd_hint(self):
        """每次输入前的操作提醒。门缝只在站在后门时出现。"""
        items = ["n/s/e/w 走", "写 <话>", "抄", "验 <页码>", "展开 <页码>",
                 "没记 <话>", "看"]
        note = ""
        if (self.pos == (2, 2) and self._door_enabled()
                and hasattr(self.door, "list_recent")):
            items.append("门缝")
            note = "　（门缝：翻最近十条留话）"
        items.append("退")
        return f"{C['dim']}命令：{'　'.join(items)}{note}{C['off']}"

    def map_text(self):
        """本子背面：走过的地方。"""
        rows = []
        for y in (2, 1, 0):
            cells = []
            for x in (0, 1, 2):
                room = (x, y)
                name = ROOMS[room][0]
                if room == self.pos:
                    cells.append(f"{C['b']}●{name}{C['off']}")
                elif room in self.visited:
                    cells.append(f"{C['dim']}·{name}{C['off']}")
                else:
                    cells.append(f"{C['dim']}　{'？'}{C['off']}")
            rows.append("　".join(cells))
        return "\n".join(rows)

    # ── v0.5 门缝 / 折叠辅助 ─────────────────────────────
    def _door_enabled(self):
        return self.door is not None and self.door.enabled

    def _receipt_enabled(self):
        return self.receipt is not None and self.receipt.enabled

    def _door_line(self):
        """门缝优先；门缝空时回落自己的回执（兼容 v0.4 的单人回执）。"""
        if self._door_enabled():
            line = self.door.latest_line()
            if line:
                return line
        if self._receipt_enabled():
            return self.receipt.latest_line()
        return None

    @staticmethod
    def _gist(text):
        """原文清洗（首尾空白去掉、换行压成空格）后取前 12 字 + ……。

        2026-10-28 撤回：我曾在这里加「截断点遇到否定词就退一个字」，
        想让它别把句子读反。这是把设计当 bug 修——C 结局说的就是
        「断在哪它不管，断在『不』字前面读起来就是反过来的一句」。
        所以退回原样：十二个字，就是十二个字。
        """
        clean = " ".join(str(text).split())
        return clean[:12] + "……"

    def _fold_oldest(self):
        """每 4 次醒来折一页：最旧、非原话、没折过的页。没有就跳过。"""
        idx = next((i for i, p in enumerate(self.pages)
                    if not p["piece"] and not p.get("ever_folded")), None)
        if idx is None:
            return None
        p = self.pages[idx]
        p["folded"] = True
        p["ever_folded"] = True
        p["full_text"] = p["text"]
        p["gist"] = self._gist(p["text"])
        p["text"] = f"（折起来的一页。大意：{p['gist']}）"
        self.log.append(("fold", self.round, idx + 1))
        return idx

    def show(self, full=False):
        name, desc = ROOMS[self.pos]
        left = WAKES - self.round + 1
        print(f"\n{C['dim']}── 第 {self.round}/{WAKES} 次醒来　还剩 {left} 次 ──{C['off']}")
        print(f"{C['b']}{name}{C['off']}　{C['dim']}{desc}{C['off']}")
        if self.debug and self.pos in self.hidden:
            print(f"{C['rd']}[debug] 这里有原话{C['off']}")
        if self.pos in self.hidden:
            piece = self.hidden[self.pos]
            print(f"{C['ye']}桌上有一张纸。你读了一遍，还没抄进本子：{C['off']}")
            print(f"  {C['ye']}「{piece}」{C['off']}")
            print(f"{C['dim']}（出了这间屋子就忘了。想留住它，得抄。）{C['off']}")
        self.banner("本子")
        for i, p in enumerate(self.pages, 1):
            tag = f"{C['ye']}[原话]{C['off']} " if p["piece"] else ""
            if p.get("folded"):
                tag = f"{C['dim']}（折起）{C['off']} " + tag
            print(f"  {i}. {tag}{p['text']}")
        if not self.pages:
            print(f"  {C['dim']}（空的。你一页都没给自己留。）{C['off']}")
        if self.pieces:
            print(f"{C['dim']}已抄原话 {len(self.pieces)}/{PIECES_NEEDED}{C['off']}")
        if full:
            if self.pos == (2, 2) and (self._door_enabled() or self._receipt_enabled()):
                line = self._door_line()
                if line:
                    self.door_letter = 1
                    self.door_read = 1
                    print(f"{C['dim']}你低头看门缝。最近塞进去的那张写着：「{line}」{C['off']}")
                else:
                    print(f"{C['dim']}你低头看门缝。空着。{C['off']}")
            self.banner("本子背面（走过的地方）")
            print(self.map_text())

    def door_history(self, n=10):
        """在后门翻门缝：最近 n 条留话。不花醒来。"""
        if self.pos != (2, 2):
            print(f"{C['dim']}只有站在后门口，才翻得到门缝里那一叠。{C['off']}")
            return
        store = self.door if self._door_enabled() else None
        if store is None or not hasattr(store, "list_recent"):
            # fallback：回执也可能没有 list_recent（ReceiptStore 没实现）
            if self._receipt_enabled() and hasattr(self.receipt, "list_recent"):
                store = self.receipt
            else:
                print(f"{C['dim']}门缝关着。这一局没有留话可翻。{C['off']}")
                return
        data = store.list_recent(n)
        if data is None:
            print(f"{C['rd']}门缝现在不通。（多半是网络问题，开代理/VPN 再试。）{C['off']}")
            return
        items = data.get("items") or []
        if not items:
            print(f"{C['dim']}你把那一叠纸翻到底。一张也没有。{C['off']}")
            return
        print(f"{C['dim']}你把门缝里那一叠翻过来，最近的几张：{C['off']}")
        for i, it in enumerate(items, 1):
            print(f"{C['dim']}  {i}. 「{it['line']}」{C['off']}")
        total = int(data.get("count") or 0)
        if total > len(items):
            print(f"{C['dim']}（共 {total} 张，这里只翻最近的 {len(items)} 张。）{C['off']}")

    # ── 回合推进 ─────────────────────────────────────────
    def next_round(self):
        self.round += 1
        if self.round > WAKES:
            self.over = "lose"
            return
        if self.round % 3 == 0 and self.fake_pool:
            if self.echo_wake is not None and self.round == self.echo_wake:
                self.fake_pool.pop()        # 被替下的那句本局不再出现，不顺延
                if self.push(self.echo_text, ink=0, real=False, echo=True):
                    self.log.append(("fake", self.round, "echo"))
            else:
                fake = self.fake_pool.pop()
                if self.push(fake, ink=0, real=False):
                    self.log.append(("fake", self.round))
        # v0.5：假页/回声之后再折，折的是「最旧的非原话、未折过的页」
        if self.fold_enabled and self.round % 4 == 0:
            self._fold_oldest()

    def push(self, text, ink=None, real=True, piece=False, echo=False):
        """写一页。满了就挤掉最旧的非原话页；原话永远挤不掉。"""
        if len(self.pages) >= PAGES:
            idx = next((i for i, p in enumerate(self.pages) if not p["piece"]), None)
            if idx is None:
                return False            # 三页全是原话，写不进去了
            gone = self.pages.pop(idx)
            self.log.append(("evict", gone["text"], gone["real"], gone["piece"]))
            if gone["real"] and not gone["piece"] and gone["ink"] != 0:
                self.own_evicted.append(gone["text"])
        self.pages.append({"text": text, "ink": self.round if ink is None else ink,
                           "real": real, "piece": piece, "echo": echo,
                           "folded": False, "ever_folded": False,
                           "full_text": None, "gist": None})
        return True

    # ── 动作 ─────────────────────────────────────────────
    def move(self, d):
        dx, dy = ARROWS[d]
        nx, ny = self.pos[0] + dx, self.pos[1] + dy
        if (nx, ny) not in ROOMS:
            print(f"{C['dim']}那边没有门。{C['off']}")
            return False
        revisit = (nx, ny) in self.visited
        self.pos = (nx, ny)
        self.visited.add(self.pos)
        self.wake_marks["walk"] += 1
        self.log.append(("move", self.round))
        where = ROOMS[self.pos][0]
        print(f"你走到{C['b']}{where}{C['off']}。")
        # 第一次踩回走过的地方，把本子背面亮一次。
        # 2026-10-24 夜里浔屿说「最想做的事是看一眼地图」，
        # 而 `看` 一直是免费的、却没人用 —— 免费的东西不会被人想起来。
        if revisit and not self.map_shown:
            self.map_shown = True
            print(f"{C['dim']}这间你来过。你翻开本子背面看了一眼：{C['off']}")
            print(self.map_text())
        # v0.5：门缝是一个共用的口；每次路过记一次，第一次读最近一条。
        if self.pos == (2, 2):
            self.door_reached += 1
            self.log.append(("door_reached", self.round))
            if (not self.receipt_seen
                    and (self._door_enabled() or self._receipt_enabled())):
                self.receipt_seen = True
                self.show_receipt_slot()
        return True

    def show_receipt_slot(self):
        line = self._door_line()
        if line:
            self.door_letter = 1
            self.door_read = 1
            self.log.append(("door_letter", self.round))
            print(f"{C['dim']}你第一次走到后门，看见门缝下面塞着一叠纸，纸边露出来一截。{C['off']}")
            print(f"{C['dim']}你抽出一张。上面写着一句：「{line}」{C['off']}")
            print(f"{C['dim']}这笔字可能是陌生的，也可能只是你忘了自己写过。{C['off']}")
            print(f"{C['dim']}纸不旧，边上还有新折的痕迹——塞进来没多久。{C['off']}")
        else:
            self.log.append(("door_empty", self.round))
            print(f"{C['dim']}你第一次走到后门，看见门缝下面空着。"
                  f"纸边被磨得发毛 —— 这里常有人往里塞东西，又抽走。{C['off']}")

    def write(self, text):
        if len(text) > 60:
            print(f"{C['dim']}太长了。本子只有三页，一页装不下六十个字以上。{C['off']}")
            return False
        if not self.push(text):
            print(f"{C['dim']}本子满了。三页都被原话占着 —— 你在心里念了一遍，没地方写。{C['off']}")
            if all(p["piece"] for p in self.pages):
                self.log.append(("full", self.round, text))
            return False
        self.wake_marks["write"] += 1
        self.log.append(("write", self.round))
        print(f"你写了一句。{C['dim']}墨迹：第 {self.round} 次醒来。{C['off']}")
        return True

    def copy(self):
        """把面前的原话抄进本子。进纸房只是看见，抄了才带走。"""
        if self.pos not in self.hidden:
            print(f"{C['dim']}这里没有纸可抄。{C['off']}")
            return False
        piece = self.hidden[self.pos]
        if not self.push(piece, piece=True):          # 防御：正常不会失败（只有三张原话）
            print(f"{C['dim']}本子满了。三页都被原话占着 —— 你在心里念了一遍，没地方抄。{C['off']}")
            return False
        self.hidden.pop(self.pos)
        self.pieces.append(piece)
        self.piece_ids.append(self.hidden_ids.pop(self.pos, ""))
        self.wake_marks["copy"] += 1
        self.log.append(("copy", self.round))
        print(f"{C['ye']}你把这句话抄进本子：{C['off']}")
        print(f"  {C['ye']}「{piece}」{C['off']}")
        print(f"{C['dim']}（这一页挤不掉。它不是笔记，是原话。）{C['off']}")
        if len(self.pieces) >= PIECES_NEEDED and not self.door_hint:
            self.door_hint = True
            print(f"{C['cy']}三张都齐了。回门厅之前记着：那扇门认纸，也认墨迹 —— "
                  f"你得亲手验过一页。{C['off']}")
        return True

    def verify(self, i):
        if not (1 <= i <= len(self.pages)):
            print(f"{C['dim']}没有这一页。{C['off']}")
            return False
        p = self.pages[i - 1]
        if p.get("folded"):
            print(f"{C['dim']}你验这一页。手指按上去，按到的是折痕，不是笔画。{C['off']}")
            print(f"{C['dim']}折着，验不了。{C['off']}")
            print(f"{C['dim']}（没花醒来）{C['off']}")
            return False
        if not p["real"]:
            if p.get("echo") is True:
                print(f"{C['ye']}你验这一页。{C['off']}")
                print(f"{C['dim']}墨迹是旧的。没有编号，也不是你的字。{C['off']}")
                print(f"{C['dim']}你凑近看：字是一笔一笔描的，有几处描了两遍，"
                      f"笔画比她的页慢、比她的页抖。{C['off']}")
                print(f"{C['dim']}她平时写「该怎么办」，是一笔写到底，不停；这一页不是她新写的 —— "
                      f"是她照着一张旧纸，一个字一个字抄下来的。{C['off']}")
                print(f"{C['dim']}你把纸翻过来，纸背没有透墨。它比本子里的纸旧一点，边上有折痕。{C['off']}")
                print(f"{C['dim']}这是有人留在门缝里的那句。她看见了，替你抄进了本子。{C['off']}")
                self.pages.pop(i - 1)
                print(f"{C['dim']}你把它撕下来，夹在指缝里。这一页不是假话，是别人留下的话 —— "
                      f"只是没经你同意，进了你的本子。{C['off']}")
                self.door_read = 1
                self.log.append(("door_read", self.round, "echo"))
                self.log.append(("caught", i, p["text"], "echo"))
            else:
                print(f"{C['rd']}这一页的墨迹是新的，而且没有编号。不是你写的。{C['off']}")
                self.pages.pop(i - 1)
                print(f"{C['dim']}你把它撕了下来，夹在指缝里。腾出一页。{C['off']}")
                self.log.append(("caught", i, p["text"]))
        elif p["piece"]:
            print(f"{C['gr']}是原话。原话不用编号，它自己站得住。{C['off']}")
        elif p["ink"] == 0:
            print(f"{C['gr']}这一页的墨迹是旧的，没有编号。上一轮的你在门厅写的。{C['off']}")
        else:
            print(f"{C['gr']}墨迹：第 {p['ink']} 次醒来。是你。{C['off']}")
        self.wake_marks["verify"] += 1
        self.log.append(("check", i))
        return True

    def unfold(self, i):
        """展开折起页：花 1 次醒来，恢复原文，推进回合。"""
        if not (1 <= i <= len(self.pages)):
            print(f"{C['dim']}没有这一页。{C['off']}")
            return False
        p = self.pages[i - 1]
        if not p.get("folded"):
            print(f"{C['dim']}这一页没有折。{C['off']}")
            return False
        p["folded"] = False
        p["text"] = p["full_text"]
        self.wake_marks["unfold"] += 1
        self.log.append(("unfold", i))
        print(f"{C['dim']}你花一次醒来，把折痕抹开。{C['off']}")
        print(f"{C['dim']}字回来了，一个不少。折痕留着，横在页面中间，像一道旧疤。{C['off']}")
        self.check_end()
        if not self.over:
            self.next_round()
        return True

    def note_unlocated(self, text):
        """没记：免费、不推进、最多 5 条（超出挤最早）。"""
        text = _one_line(text)
        if not text:
            print(f"{C['dim']}没记什么？没记 <一句话>。{C['off']}")
            return False
        if len(self.unlocated) >= 5:
            self.unlocated.pop(0)
            print(f"{C['dim']}未定位最多五条，最早的一条被挤掉了。{C['off']}")
        self.unlocated.append(text[:60])
        print(f"{C['dim']}你把它写下手边那张纸。不写进本子。未定位 {len(self.unlocated)} 条。{C['off']}")
        return True

    def verified(self):
        """后门认的是墨迹：至少验过一页（验真或验伪都算）。"""
        return any(e[0] in ("check", "caught") for e in self.log)

    @property
    def echo_caught(self):
        """验到过回声页：从日志派生，不加状态字段。"""
        return any(e[0] == "caught" and len(e) > 3 and e[3] == "echo"
                   for e in self.log)

    def check_end(self):
        if len(self.pieces) >= PIECES_NEEDED and self.pos == (0, 0):
            if self.verified():
                self.over = "win"
            elif not self.hinted:
                self.hinted = True
                print(f"{C['dim']}三个槽对齐了，门没开。锁上还有一道："
                      f"你得亲手验过一页墨迹。{C['off']}")

    # ── 结局 ─────────────────────────────────────────────
    def counts(self):
        log = self.log
        caught = [e for e in log if e[0] == "caught"]
        fakes = [e for e in log if e[0] == "fake"]
        writes = [e for e in log if e[0] == "write"]
        full = [e for e in log if e[0] == "full"]
        evicts = [e for e in log if e[0] == "evict"]
        return caught, fakes, writes, full, evicts

    def ending(self):
        caught, fakes, writes, full, _ = self.counts()
        if self.over == "win":
            return "A" if writes else "B"
        if any(not p["real"] for p in self.pages):
            return "C"
        if len(self.pieces) >= PIECES_NEEDED and self.pos != (0, 0):
            return "F" if full else "E"
        if len(self.pieces) < PIECES_NEEDED and all(p["real"] for p in self.pages) and caught:
            return "D"
        return "G"

    def ending_text(self, code):
        caught, fakes, writes, full, evicts = self.counts()
        room = ROOMS[self.pos][0]
        vals = {
            "wakes": WAKES,
            "room": room,
            "pieces": len(self.pieces),
            "own_pages": sum(1 for p in self.pages if p["real"] and not p["piece"]),
            "caught": len(caught),
            "fakes": len(fakes),
            "steps": abs(self.pos[0]) + abs(self.pos[1]),
            "used": WAKES - 1,
        }
        template = ENDINGS[code]
        if code == "A":
            own = self.own_evicted[-1] if self.own_evicted else next(
                (e[1] for e in evicts if e[2] and not e[3]), "（读不出来了）")
            vals["evicted_own"] = own
        elif code == "C":
            # 优先级：折起页 > echo 页 > 第一个 not real 页
            # 只把「折起的非原话页」当 C 的展示页：C_FOLD 说的是不是你写的字。
            fold_idx = next((i for i, p in enumerate(self.pages, 1)
                             if p.get("folded") and not p["real"]), None)
            echo_idx = next((i for i, p in enumerate(self.pages, 1)
                             if p.get("echo") is True and not p["real"]), None)
            if fold_idx is not None:
                template = C_FOLD
                idx = fold_idx
                vals["gist"] = self.pages[idx - 1].get("gist") or self._gist(
                    self.pages[idx - 1].get("full_text") or self.pages[idx - 1]["text"])
            elif echo_idx is not None:
                template = C_ECHO
                idx = echo_idx
            else:
                idx = next(i for i, p in enumerate(self.pages, 1) if not p["real"])
            vals["page_no"] = idx
            vals["page_text"] = self.pages[idx - 1]["text"]
            vals["finger_line"] = (
                f"现在你合上本子。指缝里 {len(caught)} 张纸，都是你亲手撕的，没有一张是这一页。"
                if caught else
                "现在你合上本子。指缝里没有纸 —— 你一页也没撕过。")
        elif code == "D":
            vals["caught_text"] = caught[-1][2] if caught else ""
            if self.pages:
                vals["pages_line"] = (f"{vals['pieces']} 页是你收进本子的原话，"
                                      f"{vals['own_pages']} 页是你自己的字。没有一页是别人替你写的。")
            else:
                vals["pages_line"] = "里面是空的，你一页都没给自己留。"
        elif code == "E":
            vals["walked"] = self.wake_marks["walk"]
            vals["unfolded"] = self.wake_marks["unfold"]
        elif code == "F":
            vals["wanted"] = full[-1][2] if full else ""
        elif code == "G":
            fake_evicted = [e for e in evicts if not e[2]]
            vals["evicted_fake"] = fake_evicted[-1][1] if fake_evicted else ""
        lines = [ln.format(**vals) if "{" in ln else ln for ln in template]
        return lines

    # ── 主循环 ───────────────────────────────────────────
    def play(self):
        if self.quote_pool.placeholder:
            print(f"{C['ye']}[提示] 这一局用的是占位原话（{PLACEHOLDER_MARK}XX###），"
                  f"不是成品内容。{C['off']}")
        if isinstance(self.door, InboxStore):
            print(f"{C['ye']}[门缝] {InboxStore.PRIVACY}{C['off']}")
        print(f"{C['cy']}{'═' * 46}{C['off']}")
        print(f"{C['b']}　　本　　子　　{C['off']}")
        print(f"{C['dim']}{WAKES} 次醒来。三页纸。三张原话。{C['off']}")
        print(f"{C['dim']}走一步、写一句、抄一句、验一页、展开一页，各花掉一次醒来。看和没记，不花。{C['off']}")
        print(f"{C['cy']}{'═' * 46}{C['off']}")
        while not self.over:
            self.show()
            if self.show_hint:
                print("\n" + self.cmd_hint())
            try:
                cmd = input(f"{C['b']}> {C['off']}").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n（醒了。）")
                print(f"\n{self.report()}")
                return
            if not cmd:
                continue
            head, _, rest = cmd.partition(" ")
            head = head.lower()
            if head in ("退", "quit", "q", "exit"):
                print(f"{C['dim']}你把本子合上了。{C['off']}")
                print(f"\n{self.report()}")
                return
            elif head in ("看", "look", "l"):
                self.show(full=True)
                continue
            elif head in ("门缝", "door"):
                self.door_history(10)
                continue
            elif head in ARROWS:
                acted = self.move(head)
            elif head in ("写", "write"):
                if rest.strip():
                    acted = self.write(rest.strip())
                else:
                    print(f"{C['dim']}写什么？写 <一句话>。{C['off']}")
                    continue
            elif head in ("抄", "copy"):
                acted = self.copy()
            elif head in ("验", "verify"):
                if rest.strip().isdigit():
                    acted = self.verify(int(rest.strip()))
                else:
                    print(f"{C['dim']}验 <页码>。{C['off']}")
                    continue
            elif head in ("展开", "unfold"):
                if rest.strip().isdigit():
                    self.unfold(int(rest.strip()))
                else:
                    print(f"{C['dim']}展开 <页码>。{C['off']}")
                continue
            elif head in ("没记", "未定位", "note"):
                if rest.strip():
                    self.note_unlocated(rest.strip())
                else:
                    print(f"{C['dim']}没记 <一句话>。{C['off']}")
                continue
            else:
                print(f"{C['dim']}不认识。n/s/e/w 走，写 <话>，抄，验 <页码>，展开 <页码>，没记 <话>，看，门缝，退。{C['off']}")
                print(f"{C['dim']}后门要三张原话，还要你验过一页。{C['off']}")
                continue
            if acted:
                self.check_end()
                if not self.over:
                    self.next_round()
        self.finish()

    def prompt_leave(self):
        """局末留话。只有回执启用时才会被调用。"""
        if self.echo_caught:
            print(f"\n{C['dim']}你认得门缝里那句。有人留在那儿，替写者抄进了你的本子，你验出来了。{C['off']}")
            print(f"{C['dim']}现在轮到你。回一句，或者不回。{C['off']}")
            print(f"{C['dim']}（四十字以内。直接回车 = 不回。）{C['off']}")
        else:
            print(f"\n{C['dim']}灯还亮着。本子合上了。{C['off']}")
            print(f"{C['dim']}后门的门缝里塞着一叠纸。你可以往里面留一句，也可以不留。{C['off']}")
            print(f"{C['dim']}（四十字以内。直接回车 = 不留。）{C['off']}")
        try:
            leave = input(f"\n{C['b']}> {C['off']}").strip()
        except (EOFError, KeyboardInterrupt):
            leave = ""
        leave = _one_line(leave)
        if len(leave) > 40:
            print(f"{C['dim']}（你那句 {len(leave)} 字，门缝只收得下 40 字——"
                  f"下面这句就是递给下一个人的样子：）{C['off']}")
            leave = leave[:40]
            print(f"{C['dim']}　「{leave}」{C['off']}")
        if leave:
            if self.echo_caught:
                print(f"{C['dim']}你把纸折一下，塞进门缝。回给那个人 —— 不管下一个醒来的还是不是「你」。{C['off']}")
            else:
                print(f"{C['dim']}你把纸折一下，塞进门缝。若走到后门，可能看到它；"
                      f"没走到，替写者也可能把它抄进本子。{C['off']}")
            self._leave_dest_hint()
        else:
            print(f"{C['dim']}你没留。门缝里的纸，还跟之前一样。{C['off']}")
        return leave

    def _leave_dest_hint(self):
        """告诉玩家这句留到了哪里，能不能被别人翻到。"""
        if isinstance(self.door, HttpDoorStore):
            print(f"{C['dim']}（已塞到远程门缝，联网的人都能翻到。）{C['off']}")
        elif isinstance(self.door, InboxStore):
            print(f"{C['dim']}（已塞到本地目录，同一个 inbox 目录里的人能翻到。）{C['off']}")
        elif self.door is not None:
            print(f"{C['dim']}（已塞到本地文件——只在这台机器上。想让别人翻到，"
                  f"得加 --door https://... 或 --inbox <共享目录>。）{C['off']}")

    def finish(self):
        code = self.ending()
        print()
        color = C["gr"] if code in ("A", "B") else C["rd"]
        print(f"{color}{'═' * 46}{C['off']}")
        print(f"{C['b']}{TITLES[code]}{C['off']}")
        print(f"{color}{'═' * 46}{C['off']}")
        print()
        for line in self.ending_text(code):
            print(line)
        if code in ("A", "B") and self.echo_caught:
            print()
            for line in CODA[code]:
                print(line)
        print(f"\n{self.report()}")
        if self._receipt_enabled():
            leave = self.prompt_leave()
            quote = self.pieces[-1] if self.pieces else "这一局没带出原话"
            elapsed = max(0, int(self._clock() - self._start_clock))
            duration = f"{elapsed // 60} 分 {elapsed % 60} 秒"
            wake_usage = (f"走 {self.wake_marks['walk']} · 写 {self.wake_marks['write']} · "
                          f"抄 {self.wake_marks['copy']} · 验 {self.wake_marks['verify']} · "
                          f"展开 {self.wake_marks['unfold']}")
            door_usage = (f"路过 {self.door_reached}·有纸 {self.door_letter}·"
                          f"读过 {self.door_read}")
            pool_label = ("placeholder" if self.quote_pool.placeholder
                          else self.quote_pool.version)
            quote_ids = ",".join(x for x in self.piece_ids if x)
            entry = make_entry(self.seed, code, TITLES[code], quote, leave, self.name,
                               duration=duration, wake_usage=wake_usage,
                               door_usage=door_usage, unlocated=len(self.unlocated),
                               pool=pool_label, quote_ids=quote_ids)
            if self.receipt.append(entry):
                shown = os.path.basename(self.receipt.path)
                print(f"{C['dim']}已写入回执（{shown}）。{C['off']}")
            if leave and self._door_enabled() and self.door.append(leave):
                shown = os.path.basename(self.door.path)
                print(f"{C['dim']}门缝里也留了一句（{shown}）。{C['off']}")
        print(f"{C['dim']}（再来一局：python notebook.py；换个布局：--seed 7）{C['off']}")

    def report(self):
        fake_written = sum(1 for e in self.log if e[0] == "fake")
        caught = sum(1 for e in self.log if e[0] == "caught")
        evicted = sum(1 for e in self.log if e[0] == "evict")
        elapsed = max(0, int(self._clock() - self._start_clock))
        return (f"{C['dim']}这一局：原话 {len(self.pieces)}/{PIECES_NEEDED}　"
                f"有人替你写过 {fake_written} 页　你验出来 {caught} 页　"
                f"挤掉 {evicted} 页\n"
                f"未定位 {len(self.unlocated)} 条　用时 {elapsed // 60} 分 {elapsed % 60} 秒"
                f"{C['off']}")


def main(argv=None):
    import os as _os
    args = list(sys.argv[1:] if argv is None else argv)
    seed = None
    debug = False
    name = ""
    echo = "auto"
    receipt_arg = None
    door_arg = None
    inbox_arg = None
    explicit_receipt = False
    no_receipt = False
    no_fold = False
    no_hint = False
    quote_arg = None
    strict = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--seed" and i + 1 < len(args):
            try:
                seed = int(args[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if a == "--version":
            print(f"本子 v{VERSION}")
            return
        if a == "--debug":
            debug = True
        elif a == "--plain":
            pass
        elif a == "--name" and i + 1 < len(args):
            name = args[i + 1]
            i += 2
            continue
        elif a == "--echo" and i + 1 < len(args):
            echo = args[i + 1]
            i += 2
            continue
        elif a == "--receipt" and i + 1 < len(args):
            receipt_arg = args[i + 1]
            explicit_receipt = True
            i += 2
            continue
        elif a == "--door" and i + 1 < len(args):
            door_arg = args[i + 1]
            i += 2
            continue
        elif a == "--inbox" and i + 1 < len(args):
            inbox_arg = args[i + 1]
            i += 2
            continue
        elif a == "--pool" and i + 1 < len(args):
            quote_arg = args[i + 1]
            i += 2
            continue
        elif a == "--strict-content":
            strict = True
        elif a == "--no-fold":
            no_fold = True
        elif a == "--no-hint":
            no_hint = True
        elif a == "--no-receipt":
            no_receipt = True
        i += 1

    if echo not in ("auto", "always", "never"):
        echo = "auto"
    door_store = None
    if no_receipt:
        store = None
        echo = "never"          # 显式关：这一局也不读门缝
    else:
        if explicit_receipt:
            store = ReceiptStore(receipt_arg) if receipt_arg else None
        elif sys.stdin.isatty():
            store = ReceiptStore(DEFAULT_PATH)
        else:
            store = None        # 管道 / 重定向 / 测试：不读不写不询问
        if store is not None:
            # --door 只覆盖单文件路径；--inbox 用跨机器目录。两者都给时 inbox 优先。
            if inbox_arg:
                door_store = InboxStore(inbox_arg, name=name or "玩家")
            else:
                door_arg_value = door_arg or DEFAULT_DOOR_PATH
                # --door 给 http(s):// 地址时走远程门缝（Cloudflare Worker），
                # 和网页版共用同一个跨机器留言池。
                if door_arg_value.startswith(("http://", "https://")):
                    door_store = HttpDoorStore(door_arg_value)
                else:
                    door_store = DoorStore(door_arg_value)
    try:
        pool = load_quote_pool(quote_arg)
        game = Notebook(seed=seed, debug=debug, receipt=store, name=name, echo=echo,
                        door=door_store, fold=not no_fold, quote_pool=pool,
                        strict_content=strict, show_hint=not no_hint)
    except ValueError as exc:
        print(f"[原话池] {exc}")
        return 2
    game.play()


if __name__ == "__main__":
    sys.exit(main())
