#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本子 v0.5（原话池 + 跨机器门缝）—— 自动化测试

    python test_notebook.py

安静跑完：只报每组通过数，失败项逐条列出。全过退出 0，否则退出 1。
v0.3.1 的旧语义回归全部保留；新增回执/留话/回声/CLI/原话池/跨机器门缝组。
所有临时文件都放本目录下的 `_tmp`（系统 tempfile / mkdtemp 在本沙箱会挂起或 ACL 拒绝）。
"""
import builtins
import contextlib
import http.server
import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import threading
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
NOTEBOOK = os.path.join(HERE, "notebook.py")
if not os.path.exists(NOTEBOOK):
    NOTEBOOK = os.path.join(HERE, "notebook.py")
TMP_BASE = os.path.join(HERE, "_tmp")


def tmpdir(name):
    """固定父目录 _tmp 下的子目录；不用 mkdtemp/TemporaryDirectory（ACL 坑）。"""
    os.makedirs(TMP_BASE, exist_ok=True)
    d = os.path.join(TMP_BASE, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d

_spec = importlib.util.spec_from_file_location("nb", NOTEBOOK)
nb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nb)

GROUPS = []      # [标题, 总数, 通过数]
FAILS = []


def group(title):
    GROUPS.append([title, 0, 0])


def check(name, cond, detail=""):
    g = GROUPS[-1]
    g[1] += 1
    if cond:
        g[2] += 1
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def quiet(fn, *args, **kwargs):
    """调用并吞掉游戏输出，返回 (返回值, 输出文本)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


def run(args, stdin):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, NOTEBOOK, *args],
        input=stdin, capture_output=True, text=True, encoding="utf-8", env=env,
    )


def path_to(start, goal):
    """从 start 走到 goal 的最短方向序列。"""
    q = deque([(start, [])])
    seen = {start}
    while q:
        (x, y), steps = q.popleft()
        if (x, y) == goal:
            return steps
        for d in "nsew":
            dx, dy = nb.ARROWS[d]
            nxt = (x + dx, y + dy)
            if nxt in nb.ROOMS and nxt not in seen:
                seen.add(nxt)
                q.append((nxt, steps + [d]))
    return []


def walk(g, steps):
    """按 play() 的规则逐步走：成功才结算、才推进醒来次数。"""
    for d in steps:
        acted, _ = quiet(g.move, d)
        if acted:
            g.check_end()
            if not g.over:
                g.next_round()


def test_api():
    group("API 规则")

    g = nb.Notebook(seed=1)
    hidden = list(g.hidden.keys())
    check("开局本子只有 1 页", len(g.pages) == 1)
    check("开局站在门厅", g.pos == (0, 0))
    check("开局是第 1 次醒来", g.round == 1)
    check("三张原话各有其屋", len(hidden) == 3 and len(set(g.hidden.values())) == 3)
    check("门厅里不藏原话", (0, 0) not in hidden)

    acted, out = quiet(g.move, "s")
    check("撞墙返回 False", acted is False)
    check("撞墙不移动", g.pos == (0, 0))
    check("撞墙有提示", "那边没有门" in out)

    g = nb.Notebook(seed=1)
    walk(g, path_to((0, 0), hidden[0]))
    check("进隐藏房 pieces 仍 0（不自动抄）", len(g.pieces) == 0)
    check("进隐藏房纸仍在桌上", hidden[0] in g.hidden)
    ok, out = quiet(g.copy)
    check("抄写成功", ok is True)
    check("抄后 pieces=1", len(g.pieces) == 1)
    check("抄后 hidden 移除", hidden[0] not in g.hidden)
    check("原话落成了本子的一页", any(p["piece"] and p["text"] in g.quote_pool.texts() for p in g.pages))
    check("抄写写了 copy 日志", any(e[0] == "copy" for e in g.log), str(g.log[-1:]))

    g = nb.Notebook(seed=2)
    round_before = g.round
    ok, out = quiet(g.copy)
    check("没有纸时抄：返回 False", ok is False)
    check("没有纸时抄：不花醒来", g.round == round_before)

    # 抄到第三张时提示一次「门认墨迹」——不然第一次玩的人在门口才明白，那时已经晚一步
    g = nb.Notebook(seed=13)
    g.hidden = {(0, 1): "甲", (1, 1): "乙", (0, 2): "丙"}
    for pos in [(0, 1), (1, 1)]:
        g.pos = pos
        ok, out = quiet(g.copy)
        check(f"抄第 {len(g.pieces)} 张：不出门前提示", "认墨迹" not in out)
    g.pos = (0, 2)
    ok, out = quiet(g.copy)
    check("抄到第三张：提示门认墨迹", "认墨迹" in out)
    check("只要三张齐就记下提示过", g.door_hint is True)

    g = nb.Notebook(seed=2)
    ok, out = quiet(g.copy)
    check("没有纸时抄：有提示", "没有纸可抄" in out)

    # 2026-10-24 夜加：踩回走过的屋子，第一次自动亮出本子背面
    g = nb.Notebook(seed=2)
    check("开局没亮过地图", g.map_shown is False)
    walk(g, ["n"])
    check("走进新屋子不亮地图", g.map_shown is False)
    ok, out = quiet(lambda: g.move("s"))
    check("踩回旧屋：亮地图", g.map_shown is True and "你来过" in out)
    ok, out = quiet(lambda: g.move("n"))
    check("地图只亮一次", g.map_shown is True and "你来过" not in out)

    g = nb.Notebook(seed=2)
    room = next(iter(g.hidden))
    walk(g, path_to((0, 0), room))
    # 找一间不是纸房的邻屋，离开再回来
    for d in "nsew":
        dx, dy = nb.ARROWS[d]
        nxt = (g.pos[0] + dx, g.pos[1] + dy)
        if nxt in nb.ROOMS and nxt not in g.hidden:
            walk(g, [d])
            break
    check("不抄离开：纸还在", room in g.hidden)
    walk(g, path_to(g.pos, room))
    check("重进纸房：还能看见", room in g.hidden)
    ok, _ = quiet(g.copy)
    check("重进纸房：能抄", ok is True)
    walk(g, path_to(g.pos, room))
    check("抄过再回：不再有纸", room not in g.hidden)

    # 防御分支：本子三页全是原话时，抄写失败且不花醒来、不丢纸
    g = nb.Notebook(seed=4)
    g.pages = [{"text": p, "ink": 0, "real": True, "piece": True} for p in nb.PIECES]
    g.pieces = list(nb.PIECES)
    g.pos = (1, 1)
    g.hidden = {(1, 1): "第四张？"}
    round_before = g.round
    ok, out = quiet(g.copy)
    check("满本抄写：返回 False", ok is False)
    check("满本抄写：不花醒来", g.round == round_before)
    check("满本抄写：纸没丢", (1, 1) in g.hidden)
    check("满本抄写：pieces 没变", len(g.pieces) == 3)

    g = nb.Notebook(seed=2)
    for t in ("甲甲", "乙乙", "丙丙"):
        quiet(g.write, t)
    oldest = g.pages[0]["text"]
    quiet(g.write, "丁丁")
    check("写满后挤掉最老一页", oldest not in [p["text"] for p in g.pages])
    check("本子始终只有 3 页", len(g.pages) == 3)

    g = nb.Notebook(seed=3)
    quiet(g.push, "原话A", piece=True)
    quiet(g.push, "笔记乙")
    quiet(g.push, "笔记丙")
    quiet(g.write, "笔记丁")
    check("原话不会被挤掉", any(p["text"] == "原话A" for p in g.pages))

    g = nb.Notebook(seed=4)
    for t in ("p1", "p2", "p3"):
        quiet(g.push, t, piece=True)
    ok, out = quiet(g.write, "再写一句")
    check("三页全是原话时写不进去", ok is False and "本子满了" in out)

    g = nb.Notebook(seed=5)
    for _ in range(12):
        g.next_round()
    fakes = [e[1] for e in g.log if e[0] == "fake"]
    check("伪页在第 3/6/9/12 次醒来出现", fakes == [3, 6, 9, 12], str(fakes))

    g = nb.Notebook(seed=6)
    g.next_round()                       # 走到第 2 次醒来
    check("第 1、2 次醒来没有伪页", g.round == 2 and not [e for e in g.log if e[0] == "fake"])

    g = nb.Notebook(seed=7)
    g.next_round()
    g.next_round()                       # 走到第 3 次醒来，伪页出现
    fake_idx = next(i for i, p in enumerate(g.pages) if not p["real"])
    ok, out = quiet(g.verify, fake_idx + 1)
    check("验伪页：撕掉", ok and len(g.pages) == 1)
    check("验伪页：说明不是你写的", "不是你写的" in out)

    g = nb.Notebook(seed=8)
    quiet(g.write, "我的笔记")
    ok, out = quiet(g.verify, 2)
    check("验真笔记：保留", ok and len(g.pages) == 2)
    check("验真笔记：认出是自己", "是你" in out)

    g = nb.Notebook(seed=9)
    quiet(g.push, "原话X", piece=True)
    ok, out = quiet(g.verify, 2)
    check("验原话：保留并认出", ok and len(g.pages) == 2 and "原话不用编号" in out)

    g = nb.Notebook(seed=10)
    ok, out = quiet(g.verify, 1)
    check("B1 回归：开局验第 1 页不撕", ok and len(g.pages) == 1)
    check("B1 回归：不再误判为伪造", "不是你写的" not in out)
    check("B1 回归：说明是上一轮的自己", "旧的" in out)

    g = nb.Notebook(seed=11)
    ok, out = quiet(g.verify, 9)
    check("验不存在的页：失败并提示", ok is False and "没有这一页" in out)
    check("验不存在的页：不留痕", not any(e[0] == "check" for e in g.log))

    g = nb.Notebook(seed=12)
    ok60, _ = quiet(g.write, "字" * 60)
    ok61, out61 = quiet(g.write, "字" * 61)
    check("60 字可以写", ok60 is True)
    check("61 字被拒绝并提示", ok61 is False and "太长了" in out61)

    # v0.3：后门要三张原话，还要你亲手验过一页
    g = nb.Notebook(seed=13)
    g.pieces = ["a", "b", "c"]
    ok, out = quiet(g.check_end)
    check("3 原话在门厅但没验过：不赢", g.over is None)
    check("3 原话没验过：门提示第二道锁", "验过一页" in out)
    quiet(g.check_end)
    check("提示只出一次", g.hinted is True)

    g = nb.Notebook(seed=13)
    g.pieces = ["a", "b", "c"]
    quiet(g.verify, 1)                   # 验的是开场页，也算验过
    g.check_end()
    check("验过一页（哪怕验的是开场页）：赢", g.over == "win")

    g = nb.Notebook(seed=13)
    g.pieces = ["a", "b", "c"]
    quiet(g.verify, 1)
    g.pos = (1, 1)
    g.check_end()
    check("验过了但不在门厅：不赢", g.over is None)

    g = nb.Notebook(seed=13)
    g.pieces = ["a", "b", "c"]
    g.pos = (1, 1)
    g.check_end()
    check("3 原话但不在门厅：没赢", g.over is None)

    g = nb.Notebook(seed=13)
    g.pieces = ["a", "b"]
    g.check_end()
    check("2 原话在门厅：没赢", g.over is None)

    g = nb.Notebook(seed=13)
    for _ in range(nb.WAKES):
        g.next_round()
    check("醒来耗尽判负", g.over == "lose" and g.round == nb.WAKES + 1, str(g.round))


def test_e2e():
    group("端到端（真实 stdin）")

    # 按 seed 3 的真实布局算一条最短路线；每进一间纸房先 `抄`
    g = nb.Notebook(seed=3)
    rooms = list(g.hidden.keys())

    def route_len(perm):
        cur, seq = (0, 0), []
        for r in perm:
            p = path_to(cur, r)
            seq += p
            cur = r
        back = path_to(cur, (0, 0))
        return len(seq) + len(back), seq + back

    seq = min((route_len(p) for p in itertools.permutations(rooms)), key=lambda t: t[0])[1]
    cmds, pos, copied = [], (0, 0), set()
    for d in seq:
        cmds.append(d)
        dx, dy = nb.ARROWS[d]
        pos = (pos[0] + dx, pos[1] + dy)
        if pos in rooms and pos not in copied:
            cmds.append("抄")
            copied.add(pos)
            if len(copied) == 1:                # v0.3：抄完第一张顺手验它（后门要验过一页）
                cmds.append("验 2")
    r = run(["--plain", "--seed", "3"], "\n".join(cmds) + "\n")
    out = r.stdout
    check("胜局：退出码 0", r.returncode == 0)
    check("胜局：后门开了", "后门开了" in out)
    check("胜局：已抄原话 3/3", "已抄原话 3/3" in out)
    check("胜局：验过一页（原话）", "原话不用编号" in out)
    check("胜局：撕掉 0 页", "你验出来 0 页" in out)
    check("--plain 没有颜色转义", "\x1b[" not in out)

    r = run(["--plain", "--seed", "3"], "n\ns\n" * 7)
    check("败局：醒来耗尽", r.returncode == 0 and f"第 {nb.WAKES} 次醒来用完了" in r.stdout)

    r = run(["--plain", "--seed", "2"], "s\n看\n写 " + "字" * 61 + "\n验 9\n乱打\n退\n")
    out = r.stdout
    check("无效指令：不花醒来", f"第 1/{nb.WAKES} 次醒来" in out and f"第 2/{nb.WAKES} 次醒来" not in out)
    check("无效指令：各有提示", all(k in out for k in ("那边没有门", "太长了", "没有这一页", "不认识")))
    check("帮助里提到抄", "抄" in out and "不认识" in out)
    check("退：打印结算", "这一局：原话" in out)

    r = run(["--plain", "--seed", "13"], "验 1\n看\n退\n")
    out = r.stdout
    check("B1 端到端：不撕开场页", "不是你写的" not in out)
    check("B1 端到端：本子没被清空", "（空的。你一页都没给自己留。）" not in out)


def _route_cost(hidden, route, copy=True, stop_at_three=False, verify=True):
    """按固定顺序走；copy 时进纸房抄 1 次；verify 时第一次抄完顺手验一页（后门要）。"""
    pos, got, cost, done = (0, 0), set(), 0, False
    for ch in route:
        dx, dy = nb.ARROWS[ch]
        pos = (pos[0] + dx, pos[1] + dy)
        cost += 1
        if pos in hidden and pos not in got:
            got.add(pos)
            if copy:
                cost += 1
                if verify and not done:
                    cost += 1
                    done = True
                if stop_at_three and len(got) == 3:
                    cost += abs(pos[0]) + abs(pos[1])
                    return cost
    return cost


def _optimal_cost(hidden):
    best = None
    for order in itertools.permutations(hidden):
        cur, cost = (0, 0), 0
        for r in order:
            cost += abs(cur[0] - r[0]) + abs(cur[1] - r[1])
            cur = r
        cost += abs(cur[0]) + abs(cur[1]) + 4      # 3 次抄 + 1 次验
        best = cost if best is None else min(best, cost)
    return best


def test_balance():
    group("平衡性（56 布局 + 300 种子）")

    sweep = "nneeswseww"
    ham = "eennwwse"             # 8 步哈密顿，终点客厅 (1,1)
    spots = [r for r in nb.ROOMS if r != (0, 0)]
    layouts = list(itertools.combinations(spots, 3))

    full56 = sum(_route_cost({r: "x" for r in L}, sweep) <= nb.WAKES for L in layouts)
    stop56 = sum(_route_cost({r: "x" for r in L}, sweep, stop_at_three=True) <= nb.WAKES for L in layouts)
    ham56 = sum(_route_cost({r: "x" for r in L}, ham, stop_at_three=True) <= nb.WAKES for L in layouts)
    opt56 = sum(_optimal_cost({r: "x" for r in L}) <= nb.WAKES for L in layouts)

    check("56 布局：走完全程+抄 0 胜", full56 == 0, str(full56))
    check("56 布局：扫到第三张即回 35 胜", stop56 == 35, str(stop56))
    check("56 布局：8 步哈密顿 35 胜", ham56 == 35, str(ham56))
    check("56 布局：全知 56 胜", opt56 == 56, str(opt56))

    wins_full = wins_stop = wins_ham = wins_opt = 0
    bad_pages = 0
    loss_steps = {}
    opt_costs = {}
    for seed in range(300):
        hidden = dict(nb.Notebook(seed=seed).hidden)
        wins_full += _route_cost(hidden, sweep) <= nb.WAKES
        c = _route_cost(hidden, sweep, stop_at_three=True)
        if c <= nb.WAKES:
            wins_stop += 1
        else:
            # 复算第三张在第几步：用同一路线重放
            pos, got = (0, 0), set()
            for i, ch in enumerate(sweep, 1):
                dx, dy = nb.ARROWS[ch]
                pos = (pos[0] + dx, pos[1] + dy)
                if pos in hidden and pos not in got:
                    got.add(pos)
                    if len(got) == 3:
                        loss_steps[i] = loss_steps.get(i, 0) + 1
                        break
        wins_ham += _route_cost(hidden, ham, stop_at_three=True) <= nb.WAKES
        oc = _optimal_cost(hidden)
        wins_opt += oc <= nb.WAKES
        opt_costs[oc] = opt_costs.get(oc, 0) + 1
        bad_pages += len(nb.Notebook(seed=seed).pages) > nb.PAGES

    check("300 种子：走完全程+抄 0 胜", wins_full == 0, str(wins_full))
    check("300 种子：扫到第三张即回 180 胜", wins_stop == 180, str(wins_stop))
    check("300 种子：8 步哈密顿 55%–70%", 165 <= wins_ham <= 210, str(wins_ham))
    check("300 种子：全知 300 胜", wins_opt == 300, str(wins_opt))
    check("输局第三张都在第 8 步", loss_steps == {8: 120}, str(loss_steps))
    check("全知成本分布 8/10/12", opt_costs == {8: 4, 10: 108, 12: 188}, str(opt_costs))
    check("页数从不超 3", bad_pages == 0)

    # 实跑一局「走完全程 + 抄」：第 13 次成本前就耗尽，且本子不超页
    g = nb.Notebook(seed=0)
    for d in sweep:
        if g.over:
            break
        ok, _ = quiet(g.move, d)
        if ok:
            quiet(g.check_end)
            if not g.over:
                g.next_round()
        if g.pos in g.hidden and not g.over:
            ok, _ = quiet(g.copy)
            if ok:
                quiet(g.check_end)
                if not g.over:
                    g.next_round()
    check("实跑全程扫荡+抄：判负", g.over == "lose", str(g.over))
    check("实跑全程扫荡+抄：预算耗尽", g.round == nb.WAKES + 1, str(g.round))
    check("实跑全程扫荡+抄：页数≤3", len(g.pages) <= nb.PAGES)


def _pg(text, real=True, piece=False, ink=3, echo=False):
    return {"text": text, "ink": ink, "real": real, "piece": piece, "echo": echo}


def _blank(seed=1):
    g = nb.Notebook(seed=seed)
    g.pages, g.pieces, g.log = [], [], []
    return g


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@contextlib.contextmanager
def _input(value):
    """替换 input()：返回 value；若 value 是异常则抛出（模拟 EOF/Ctrl-C）。"""
    old = builtins.input

    def fake(prompt=""):
        print(prompt, end="")
        if isinstance(value, BaseException):
            raise value
        return value

    builtins.input = fake
    try:
        yield
    finally:
        builtins.input = old


def _store(name, *entries):
    d = tmpdir(name)
    path = os.path.join(d, "回执.md")
    st = nb.ReceiptStore(path)
    for e in entries:
        if not st.append(e):
            raise RuntimeError(f"预置回执失败：{path}")
    return st, path


def _entry(leave="上一局的那句话", seed=3, code="B", name="甲"):
    return nb.make_entry(seed, code, nb.TITLES[code], nb.PIECES[0], leave, name)


def _win_game(store=None, seed=3, echo="never"):
    g = nb.Notebook(seed=seed, receipt=store, echo=echo)
    g.pages = [_pg(p, piece=True) for p in nb.PIECES]
    g.pieces = list(nb.PIECES)
    g.pos = (0, 0)
    g.over = "win"
    g.log = [("check", 1)]
    return g


def _route_cmds(seed):
    """按真实布局算一条最短收纸路线；每进纸房抄，第一次抄完验一页。"""
    g = nb.Notebook(seed=seed)
    rooms = list(g.hidden)

    def one(perm):
        cur, seq = (0, 0), []
        for r in perm:
            seq += path_to(cur, r)
            cur = r
        return seq + path_to(cur, (0, 0))

    seq = min((one(p) for p in itertools.permutations(rooms)), key=len)
    cmds, pos, copied = [], (0, 0), set()
    for d in seq:
        cmds.append(d)
        dx, dy = nb.ARROWS[d]
        pos = (pos[0] + dx, pos[1] + dy)
        if pos in rooms and pos not in copied:
            cmds.append("抄")
            copied.add(pos)
            if len(copied) == 1:
                cmds.append("验 2")
    return cmds


def test_endings():
    group("七个结局")

    def case_a():
        g = _blank()
        g.pages = [_pg(p, piece=True) for p in nb.PIECES]
        g.pieces = list(nb.PIECES)
        g.over = "win"
        g.log = [("write", 2), ("evict", "我写的那句", True, False), ("fake", 3)]
        g.own_evicted = ["我写的那句"]
        return g

    def case_b():
        g = _blank()
        g.pages = [_pg(p, piece=True) for p in nb.PIECES]
        g.pieces = list(nb.PIECES)
        g.over = "win"
        g.log = [("fake", 3)]
        return g

    def case_c():
        g = _blank()
        g.pages = [_pg("上一轮的句子"), _pg("你已经想清楚了，照着感觉走就对了。", real=False, ink=0),
                   _pg(nb.PIECES[0], piece=True)]
        g.pieces = [nb.PIECES[0]]
        g.pos = (1, 2)
        g.over = "lose"
        g.log = [("evict", "旧的", True, False), ("fake", 3)]
        return g

    def case_d():
        g = _blank()
        g.pages = [_pg("我写的"), _pg(nb.PIECES[0], piece=True)]
        g.pieces = [nb.PIECES[0]]
        g.pos = (2, 1)
        g.over = "lose"
        g.log = [("write", 2), ("fake", 3), ("caught", 2, "本子上的都是你自己写的，不用验。")]
        return g

    def case_e():
        g = _blank()
        g.pages = [_pg(p, piece=True) for p in nb.PIECES]
        g.pieces = list(nb.PIECES)
        g.pos = (1, 2)
        g.over = "lose"
        g.log = [("fake", 3), ("fake", 6), ("fake", 9), ("fake", 12)]
        return g

    def case_f():
        g = case_e()
        g.pos = (2, 2)
        g.log = g.log + [("full", 13, "我想留一句自己的话。")]
        return g

    def case_g():
        g = _blank()
        g.pages = [_pg("我写的"), _pg(nb.PIECES[0], piece=True)]
        g.pieces = [nb.PIECES[0]]
        g.pos = (1, 0)
        g.over = "lose"
        g.log = [("write", 2), ("fake", 3), ("evict", "出口在北边，别再往深处去了。", False, False)]
        return g

    want = {"A": case_a, "B": case_b, "C": case_c, "D": case_d,
            "E": case_e, "F": case_f, "G": case_g}
    for code, make in want.items():
        g = make()
        got = g.ending()
        check(f"结局 {code}（{nb.TITLES[code]}）判得对", got == code, f"实际 {got}")
        lines = g.ending_text(got)
        left = [ln for ln in lines if "{" in ln or "}" in ln]
        check(f"结局 {code} 占位符填干净", not left, str(left[:1]))
        check(f"结局 {code} 有文本", len(lines) >= 10 and any(lines))

    g = case_a()
    t = "\n".join(g.ending_text("A"))
    check("A 引用了自己写的原句", "我写的那句" in t)
    g = case_c()
    t = "\n".join(g.ending_text("C"))
    check("C 引用了那页假话", "照着感觉走" in t)
    check("C 页码写对", "第 2 页" in t)
    check("C 普通不承诺「先读到」", "先读到" not in t)
    g = case_c()
    g.pages = [_pg(nb.PIECES[0], piece=True), _pg("假话", real=False, ink=0)]
    g.log = [("fake", 3)]
    t = "\n".join(g.ending_text("C"))
    check("C 没撕过纸时换成另一句", "一页也没撕过" in t)
    g = case_f()
    t = "\n".join(g.ending_text("F"))
    check("F 引用想写没写进去的那句", "我想留一句自己的话" in t)
    g = case_d()
    g.pages = []
    t = "\n".join(g.ending_text("D"))
    check("D 本子空着时兜得住", "一页都没给自己留" in t)
    g = case_g()
    t = "\n".join(g.ending_text("G"))
    check("G 引用被挤掉的假话", "出口在北边" in t)
    check("G 报出你的页数", "1 页是你的字" in t)


def test_receipt_format():
    group("回执格式与存储")

    e = nb.make_entry(3, "B", nb.TITLES["B"], "原话\n第二行", "留话\t一句", "甲")
    check("make_entry 键齐全",
          set(e) == {"ts", "who", "seed", "code", "title", "quote",
                     "leave", "note", "version"})
    check("make_entry 值压成单行",
          "\n" not in e["quote"] and "\t" not in e["leave"])
    check("空留话写成没有留话",
          nb.make_entry(3, "B", "t", "q", "")["leave"] == "没有留话")

    st, path = _store("receipt1")
    check("append 返回 True", st.append(e) is True)
    txt = _read(path)
    check("文件含机器键「批注」", "- 批注：" in txt)
    check("不再写 note / 我的批注", "note" not in txt and "我的批注" not in txt)
    check("头部只有一份", txt.count("# 本子 · 回执") == 1)
    check("条目在头部之后", txt.index("## ") > txt.index("# 本子"))
    check("没有 .tmp 残留",
          not any(".tmp." in n for n in os.listdir(os.path.dirname(path))))

    st.append(_entry("第二句", 4, "A", "乙"))
    txt = _read(path)
    check("最新条目在上", txt.index("第二句") < txt.index("留话 一句"))
    st2 = nb.ReceiptStore(path)
    check("load 出两条", len(st2.load()) == 2)
    check("latest_line 取最新留话", st2.latest_line() == "第二句")

    # 只有 HEADER、没有旧条目：不能重复写一份头
    d = tmpdir("receipt_header")
    p = os.path.join(d, "回执.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(nb.HEADER)
    stx = nb.ReceiptStore(p)
    check("只有头时 append 成功", stx.append(e) is True)
    t2 = _read(p)
    check("只有头时不重复头",
          t2.count("# 本子 · 回执") == 1 and t2.count("## ") == 1)

    # 坏条目跳过，后面的好条目保留
    d = tmpdir("receipt_bad")
    p = os.path.join(d, "回执.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(nb.HEADER)
        f.write("## 坏掉的条目\n\n- 只有一句话\n\n")
        f.write("## 2026-01-01 00:00 · 丙\n\n- seed：1\n- 结局：A · 压痕\n"
                "- 原话：q\n- 留话：l\n- 批注：\n- 版本：0.4.1\n\n")
    st3 = nb.ReceiptStore(p)
    check("坏条目跳过、好条目保留", len(st3.load()) == 1)
    check("好条目字段对", st3.entries[0]["code"] == "A" and st3.entries[0]["who"] == "丙")

    # 旧格式「我的批注」兼容，读出为 note
    d = tmpdir("receipt_old")
    p = os.path.join(d, "回执.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(nb.HEADER)
        f.write("## 2026-01-01 00:00 · 丁\n\n- seed：2\n- 结局：C · 最好听的那一页\n"
                "- 原话：q\n- 留话：l\n- 我的批注：旧注\n- 版本：0.3.1\n\n")
    st4 = nb.ReceiptStore(p)
    st4.load()
    check("旧「我的批注」读成 note", st4.entries[0]["note"] == "旧注")

    # 只有「没有留话」的条目：latest_line 为 None
    st5, _ = _store("receipt_none", _entry("", 5, "B"))
    check("没有留话时 latest_line=None", st5.latest_line() is None)

    # 写不进去：返回 False、只警告、不抛异常
    bad = nb.ReceiptStore(os.path.join(tmpdir("receipt_badpath"), "no", "回执.md"))
    ok, out = quiet(bad.append, e)
    check("写失败返回 False", ok is False)
    check("写失败只警告", "没写进去" in out)


def test_finish_receipt():
    group("留话与回执写入")

    st, path = _store("finish1")
    g = _win_game(st)
    with _input("我给下一局留一句"):
        out = quiet(g.finish)[1]
    txt = _read(path)
    check("留话写进回执", "留话：我给下一局留一句" in txt)
    check("结局写对", "结局：B · 三张别人的话" in txt)
    check("原话取最后一张", f"原话：{nb.PIECES[2]}" in txt)
    check("版本写对", "版本：0.5" in txt)
    check("名字写对", "· 你" in txt)
    check("名字最多 20 字", len(nb.make_entry(1, "A", "压痕", "q", "l", "名" * 30)["who"]) == 20)
    check("只打印文件名，不打绝对路径", "回执.md" in out and path not in out)
    check("有「可能看到它」确认句", "可能看到它" in out)

    st2, path2 = _store("finish2")
    g = _win_game(st2)
    with _input("字" * 50):
        quiet(g.finish)
    stx = nb.ReceiptStore(path2)
    stx.load()
    check("留话截到 40 字", len(stx.entries[0]["leave"]) == 40)

    st3, path3 = _store("finish3")
    g = _win_game(st3)
    with _input(EOFError()):
        out = quiet(g.finish)[1]
    stx = nb.ReceiptStore(path3)
    stx.load()
    check("EOF 不留话也写回执", len(stx.entries) == 1)
    check("EOF 留话记为没有留话", stx.entries[0]["leave"] == "没有留话")
    check("EOF 有「你没留」", "你没留" in out)

    st4, path4 = _store("finish4")
    g = _win_game(st4)
    with _input(KeyboardInterrupt()):
        quiet(g.finish)
    check("Ctrl-C 也能写回执", os.path.exists(path4))

    g = _win_game(None)
    with _input(AssertionError("没有回执却调用了 input")):
        out = quiet(g.finish)[1]
    check("无回执不询问", "已写入回执" not in out)
    check("无回执没有留话段", "（四十字以内" not in out)

    bad = nb.ReceiptStore(os.path.join(tmpdir("finish_bad"), "no", "回执.md"))
    g = _win_game(bad)
    with _input("留一句"):
        out = quiet(g.finish)[1]
    check("写失败提示不崩", "[回执] 没写进去" in out)


def test_echo_page():
    group("回声页与验回声")
    LEAVE = "上一局的那句话"
    st, path = _store("echo1", _entry(LEAVE))

    g = nb.Notebook(seed=3, receipt=st, echo="always")
    check("回声文本来自最近留话", g.echo_text == LEAVE)
    check("回声落在 3/6/9/12", g.echo_wake in (3, 6, 9, 12), str(g.echo_wake))
    check("回声独立随机流不扰动布局",
          dict(nb.Notebook(seed=7).hidden) == dict(
              nb.Notebook(seed=7, receipt=nb.ReceiptStore(path), echo="always").hidden))

    g = nb.Notebook(seed=3, receipt=st, echo="always")
    g.echo_text = LEAVE
    g.echo_wake = 3
    g.round = 2
    quiet(g.next_round)
    ep = [p for p in g.pages if p.get("echo") is True]
    check("回声页带 echo=True", len(ep) == 1)
    check("回声页 real=False、ink=0",
          ep and ep[0]["real"] is False and ep[0]["ink"] == 0)
    check("回声页文本就是留话", ep and ep[0]["text"] == LEAVE)
    check("回声替写日志是三元组", ("fake", 3, "echo") in g.log)

    idx = g.pages.index(ep[0]) + 1
    g.pos = (2, 2)
    ok, out = quiet(g.verify, idx)
    check("验回声：成功并撕掉", ok is True and not any(p.get("echo") for p in g.pages))
    check("验回声：caught 四元组", ("caught", idx, LEAVE, "echo") in g.log)
    check("echo_caught 为 True", g.echo_caught is True)
    check("验回声文案：门缝/有人留在/别人留下",
          "门缝" in out and "有人留在" in out and "别人留下" in out)

    # 普通假页：日志仍是 3 元组，echo_caught 为 False
    g2 = nb.Notebook(seed=3, receipt=None, echo="never")
    g2.round = 2
    quiet(g2.next_round)
    fi = next(i for i, p in enumerate(g2.pages, 1) if not p["real"])
    quiet(g2.verify, fi)
    check("普通假页 caught 仍是 3 元组",
          any(e[0] == "caught" and len(e) == 3 for e in g2.log))
    check("普通假页 echo_caught=False", g2.echo_caught is False)

    check("echo=never 不读回声",
          nb.Notebook(seed=3, receipt=st, echo="never").echo_text is None)

    ga = nb.Notebook(seed=3, receipt=st, echo="auto")
    check("auto 要么不回声、要么落在 3/6/9/12",
          ga.echo_wake is None or ga.echo_wake in (3, 6, 9, 12))
    check("auto 决定回声时文本存在",
          ga.echo_wake is None or ga.echo_text == LEAVE)

    # 一整局 12 次醒来：正好 4 张替写页，其中 1 张回声
    g5 = nb.Notebook(seed=3, receipt=st, echo="always")
    g5.echo_text = LEAVE
    g5.echo_wake = 12
    for _ in range(11):
        quiet(g5.next_round)
    fakes = [e for e in g5.log if e[0] == "fake"]
    check("回声局替写仍是 4 页", len(fakes) == 4, str(fakes))
    check("其中一张是 echo 三元组",
          sum(1 for e in fakes if len(e) == 3) == 1)
    check("第 12 次回声页在本子上",
          any(p.get("echo") is True for p in g5.pages))
    check("回声页仍不计 pieces", g5.pieces == [])

    # C 变体：回声页留在本子上
    g5.over = "lose"
    g5.round = nb.WAKES + 1
    txt = "\n".join(g5.ending_text("C"))
    check("C 变体选回声页", "门缝" in txt and LEAVE in txt)
    check("C 变体不重复普通结尾", "沙发上的坑早就凉了" not in txt)
    check("C 变体不改 C 判定", g5.ending() == "C")

    # C 普通：回声已经撕掉
    g6 = _blank()
    g6.pages = [_pg("普通假话", real=False, ink=0), _pg(nb.PIECES[0], piece=True)]
    g6.pieces = [nb.PIECES[0]]
    g6.pos = (1, 2)
    g6.over = "lose"
    g6.log = [("caught", 2, LEAVE, "echo")]
    t6 = "\n".join(g6.ending_text("C"))
    check("回声已撕：C 回普通文案", "门缝" not in t6)
    check("回声已撕：C 仍引用普通假页", "普通假话" in t6)

    # 普通假页 + 回声页同时存在：优先回声页
    g7 = _blank()
    g7.pages = [_pg("普通假话", real=False, ink=0),
                _pg(LEAVE, real=False, ink=0, echo=True)]
    g7.over = "lose"
    g7.round = nb.WAKES + 1
    t7 = "\n".join(g7.ending_text("C"))
    check("C 优先选回声页", "第 2 页" in t7 and LEAVE in t7)

    # A/B coda 只在验到回声时追加
    g8 = _win_game(None)
    g8.log = [("caught", 2, LEAVE, "echo")]
    out8 = quiet(g8.finish)[1]
    check("A/B coda：验到回声才追加", "你想起之前读到的那张纸" in out8)
    g9 = _win_game(None)
    out9 = quiet(g9.finish)[1]
    check("A/B coda：没验到不追加", "你想起之前读到的那张纸" not in out9)


def test_door_slot():
    group("门缝与看")

    LEAVE = "上一局的那句话"
    st, _ = _store("door1", _entry(LEAVE))
    g = nb.Notebook(seed=3, receipt=st, echo="never")
    g.pos = (1, 2)
    ok, out = quiet(g.move, "e")
    check("首次到后门：显示门缝", ok and "门缝" in out)
    check("首次到后门：显示留话", LEAVE in out)
    check("receipt_seen 置位", g.receipt_seen is True)

    quiet(g.move, "w")
    ok, out = quiet(g.move, "e")
    check("第二次到后门：不重复", "门缝" not in out)

    st2, _ = _store("door_empty")
    g2 = nb.Notebook(seed=3, receipt=st2, echo="never")
    g2.pos = (1, 2)
    ok, out = quiet(g2.move, "e")
    check("空回执显示「空着」", "空着" in out)

    g3 = nb.Notebook(seed=3)
    g3.pos = (1, 2)
    ok, out = quiet(g3.move, "e")
    check("默认无回执不显示门缝", "门缝" not in out)
    check("默认无回执 receipt_seen 不置位", g3.receipt_seen is False)

    g4 = nb.Notebook(seed=3, receipt=st, echo="never")
    g4.pos = (2, 2)
    out = quiet(g4.show, True)[1]
    check("看本子背面：后门可重读留话", LEAVE in out)

    out = quiet(g4.show, False)[1]
    check("普通「看」不读门缝", LEAVE not in out)


def test_cli():
    group("命令行与默认关闭")

    g = nb.Notebook(seed=1)
    check("默认 receipt=None", g.receipt is None)
    check("默认不读回声", g.echo_text is None and g.echo_wake is None)

    d = tmpdir("cli")
    rp = os.path.join(d, "回执.md")
    cmds = _route_cmds(3) + ["下局别抄我的"]
    r = run(["--plain", "--seed", "3", "--receipt", rp, "--name", "乙"],
            "\n".join(cmds) + "\n")
    check("--receipt 非 TTY 也写", r.returncode == 0 and os.path.exists(rp))
    txt = _read(rp)
    check("CLI 回执含留话", "留话：下局别抄我的" in txt)
    check("CLI 回执含 name", "· 乙" in txt)
    check("CLI 输出不打绝对路径", rp not in r.stdout and "回执.md" in r.stdout)

    rp2 = os.path.join(d, "不应存在.md")
    r = run(["--plain", "--seed", "3", "--no-receipt", "--receipt", rp2],
            "\n".join(cmds) + "\n")
    check("--no-receipt 优先", r.returncode == 0 and not os.path.exists(rp2))

    r = run(["--plain", "--seed", "1", "--receipt"], "退\n")
    check("--receipt 缺路径不崩、不开回执", r.returncode == 0)

    r = run(["--plain", "--version"], "")
    check("--version 打印 0.5", r.returncode == 0 and "0.5" in r.stdout)

    # 在进程内测 TTY 默认：替换 sys.stdin 与 Notebook，只检查传参
    class FakeIn:
        def isatty(self):
            return True

    class Dummy:
        last = None

        def __init__(self, **kw):
            Dummy.last = kw

        def play(self):
            pass

    old_nb, old_stdin = nb.Notebook, nb.sys.stdin
    try:
        nb.Notebook = Dummy
        nb.sys.stdin = FakeIn()
        nb.main([])
        check("TTY 默认开回执",
              Dummy.last["receipt"] is not None
              and Dummy.last["receipt"].path == nb.DEFAULT_PATH)
        nb.main(["--no-receipt"])
        check("TTY --no-receipt 关闭",
              Dummy.last["receipt"] is None and Dummy.last["echo"] == "never")
        nb.main(["--receipt", rp, "--name", "甲", "--echo", "always", "--seed", "7"])
        check("显式 --receipt 优先",
              Dummy.last["receipt"].path == rp and Dummy.last["name"] == "甲")
        check("--echo/--seed 传入",
              Dummy.last["echo"] == "always" and Dummy.last["seed"] == 7)
        nb.main(["--echo", "bogus"])
        check("非法 --echo 回 auto", Dummy.last["echo"] == "auto")
    finally:
        nb.Notebook, nb.sys.stdin = old_nb, old_stdin


def test_fold():
    group("折叠与展开")

    g = nb.Notebook(seed=3)
    check("API 默认 fold=False", not g.fold_enabled)

    g = _blank(seed=3)
    g.fold_enabled = True
    g.round, g.fake_pool = 3, []
    g.pages = [_pg("一" * 20), _pg("二" * 20), _pg("三" * 20)]
    g.next_round()
    p1 = g.pages[0]
    check("第 4 次醒来折最旧页", g.round == 4 and p1.get("folded") is True)
    check("折起页 text 是大意提示", p1["text"].startswith("（折起来的一页。大意："))
    check("gist=前 12 字+……", p1.get("gist") == "一" * 12 + "……")
    check("full_text 保存原文", p1.get("full_text") == "一" * 20)
    check("folded/ever_folded 都置位", bool(p1.get("folded")) and bool(p1.get("ever_folded")))

    g.round = 7
    g.next_round()
    check("第 8 次醒来折下一页", g.round == 8 and g.pages[1].get("folded") is True)

    before = g.round
    quiet(g.unfold, 1)
    check("展开花 1 次醒来", g.round == before + 1)
    check("展开恢复原文", g.pages[0]["text"] == "一" * 20 and not g.pages[0].get("folded"))
    check("ever_folded 保留", g.pages[0].get("ever_folded") is True)
    check("展开计数", g.wake_marks["unfold"] == 1 and ("unfold", 1) in g.log)

    g.round = 11
    g.next_round()
    check("第 12 次醒来再折一页", g.pages[2].get("folded") is True)
    check("展开过的页不再折", g.pages[0].get("folded") is False)

    g2 = _blank(seed=4)
    g2.fold_enabled = True
    g2.round, g2.fake_pool = 3, []
    g2.pages = [_pg("原话甲", piece=True), _pg("旧页乙" * 8), _pg("旧页丙" * 8)]
    g2.next_round()
    check("原话永不折", not g2.pages[0].get("folded") and g2.pages[1].get("folded"))

    g3 = _blank(seed=5)
    g3.fold_enabled = True
    g3.round, g3.fake_pool = 3, []
    g3.pages = [_pg("原话甲", piece=True), _pg("原话乙", piece=True), _pg("原话丙", piece=True)]
    g3.next_round()
    check("无候选页时折叠 no-op", all(not p.get("folded") for p in g3.pages))

    g4 = _blank(seed=6)
    g4.fold_enabled = True
    g4.round, g4.fake_pool = 3, []
    g4.pages = [_pg("整页" * 10), _pg("另一页" * 10), _pg("第三页" * 10)]
    g4.next_round()
    r0 = g4.round
    r, out = quiet(g4.verify, 1)
    check("折起页验不了", r is False)
    check("验折起页不花醒来", g4.round == r0)
    check("验折起页不记 caught", not any(e[0] == "caught" for e in g4.log))
    check("验折起页提示先展开", "折" in out)

    g5 = _blank(seed=7)
    g5.pages = [_pg("没折的页")]
    r, _ = quiet(g5.unfold, 1)
    check("展开没折的页失败且不花醒来", r is False and g5.round == 1)

    g6 = _blank(seed=8)
    g6.pieces = list(nb.PIECES)
    g6.pos, g6.over = (2, 0), "lose"
    g6.wake_marks["unfold"] = 2
    txt = "".join(g6.ending_text("E"))
    check("E 数字行含展开次数", "2 次展开" in txt)


def test_unlocated():
    group("未定位")
    g = _blank(seed=11)
    r0 = g.round
    quiet(g.note_unlocated, "门边的划痕")
    check("没记不花醒来、不推进", g.round == r0)
    check("没记进未定位", g.unlocated == ["门边的划痕"])
    check("报告显示未定位条数", "未定位 1 条" in g.report())

    for i in range(4):
        quiet(g.note_unlocated, f"线索{i}")
    check("未定位可到 5 条", len(g.unlocated) == 5)
    quiet(g.note_unlocated, "第六条")
    check("超出 5 条挤最早", len(g.unlocated) == 5 and g.unlocated[0] == "线索0")
    r, _ = quiet(g.note_unlocated, "   ")
    check("空没记被拒", r is False)
    check("没记不写页、不写本子", len(g.pages) == 0 and g.pieces == [])


def test_clock_and_fields():
    group("时钟与回执字段")
    t = [100.0]
    g = nb.Notebook(seed=1, clock=lambda: t[0])
    t[0] = 225.0
    check("报告时长用注入时钟", "2 分 5 秒" in g.report())

    st, path = _store("clock_v05")
    e = nb.make_entry(3, "B", nb.TITLES["B"], nb.PIECES[0], "下一句", "甲",
                      duration="2 分 5 秒",
                      wake_usage="走 3 · 写 1 · 抄 2 · 验 1 · 展开 1",
                      door_usage="路过 2·有纸 1·读过 1", unlocated=2)
    check("新字段 entry 带 duration", "duration" in e and e["unlocated"] == 2)
    st.append(e)
    txt = _read(path)
    check("回执含时长", "- 时长：2 分 5 秒" in txt)
    check("回执含醒来用量", "- 醒来用在哪：走 3 · 写 1 · 抄 2 · 验 1 · 展开 1" in txt)
    check("回执含门计数", "- 门：路过 2·有纸 1·读过 1" in txt)
    check("回执含未定位", "- 未定位：2 条" in txt)
    old = nb.make_entry(3, "B", nb.TITLES["B"], nb.PIECES[0], "旧", "甲")
    check("旧 entry 不强行加新字段", "duration" not in old)


def test_door_v05():
    group("门缝 v0.5")
    d = tmpdir("door_v05")
    p = os.path.join(d, "门缝", "留话.txt")
    ds = nb.DoorStore(p)
    check("门缝空时没得读", ds.latest_line() is None)
    ds.append("第一句")
    ds.append("第二句")
    check("门缝读最后一条", ds.latest_line() == "第二句")
    check("门缝无文件头、每行一条", _read(p).splitlines() == ["第一句", "第二句"])
    check("门缝拒空行", ds.append("   ") is False)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n坏行\n   \n好行\n")
    check("门缝跳过空行/读最后非空", ds.latest_line() == "好行")

    ds.append("留给下一个人")
    g = nb.Notebook(seed=1, door=ds, echo="never")
    g.pos = (1, 2)
    quiet(g.move, "e")
    check("第一次到后门看到门缝", "留给下一个人" in quiet(g.show, True)[1])
    check("门缝计数：路过/有纸/读过",
          (g.door_reached, g.door_letter, g.door_read) == (1, 1, 1))
    quiet(g.move, "w")
    quiet(g.move, "e")
    out2 = quiet(g.move, "e")[1]
    check("再路过不重复读同一条", g.door_read == 1 and "抽出一张" not in out2)

    empty = nb.DoorStore(os.path.join(d, "空门缝.txt"))
    g2 = nb.Notebook(seed=1, door=empty, echo="never")
    g2.pos = (1, 2)
    quiet(g2.move, "e")
    check("空门缝计数有纸=0", (g2.door_reached, g2.door_letter, g2.door_read) == (1, 0, 0))
    check("空门缝显示空着", "空着" in quiet(g2.show, True)[1])

    st, rp = _store("door_finish")
    g3 = _win_game(store=st)
    g3.door = ds
    before = ds.latest_line()
    with _input("留给下一个"):
        quiet(g3.finish)
    check("留话同时写回执和门缝", ds.latest_line() == "留给下一个" and "留给下一个" in _read(rp))
    check("门缝追加不覆盖旧的", before in _read(p))

    g4 = _win_game(store=None)
    g4.door = ds
    latest = ds.latest_line()
    with _input("不该写"):
        quiet(g4.finish)
    check("无回执不写门缝", ds.latest_line() == latest)

    ds.append("门缝里的回声")
    g5 = nb.Notebook(seed=1, door=ds, echo="always")
    check("回声优先读门缝", g5.echo_text == "门缝里的回声" and g5.echo_wake in (3, 6, 9, 12))

    st2, _ = _store("door_fallback", _entry())
    empty2 = nb.DoorStore(os.path.join(d, "空2.txt"))
    g6 = nb.Notebook(seed=1, receipt=st2, door=empty2, echo="always")
    check("门缝空回落自己回执", g6.echo_text == "上一局的那句话", repr(g6.echo_text))


def test_v05_cli():
    group("v0.5 命令行")
    d = tmpdir("cli_v05")
    rp = os.path.join(d, "回执.md")
    dp = os.path.join(d, "我的门缝.txt")

    class FakeIn:
        def isatty(self):
            return True

    class Dummy:
        last = None

        def __init__(self, **kw):
            Dummy.last = kw

        def play(self):
            pass

    old_nb, old_stdin = nb.Notebook, nb.sys.stdin
    try:
        nb.Notebook = Dummy
        nb.sys.stdin = FakeIn()
        nb.main([])
        check("main 默认 fold=True", Dummy.last["fold"] is True)
        nb.main(["--no-fold"])
        check("--no-fold 关折叠", Dummy.last["fold"] is False)
        nb.main(["--receipt", rp, "--door", dp])
        check("--door 覆盖门缝路径", Dummy.last["door"].path == dp)
        nb.main(["--no-receipt", "--door", dp])
        check("--no-receipt 连门缝一起关", Dummy.last["door"] is None)
    finally:
        nb.Notebook, nb.sys.stdin = old_nb, old_stdin


def test_quote_pool():
    group("原话池")
    p = nb.load_quote_pool()
    check("池子 8 条 active", len(p.active()) == 8)
    check("池子不是占位", not p.placeholder)
    check("池子版本", p.version == "原话池-v1")
    check("每条有 self/other 标签",
          all(q.get("to") in ("self", "other") for q in p.active()))

    # v0.5.1：默认池缺失时不再静默降级 —— 仍能玩，但必须说清玩的是旧三张
    import io
    import contextlib
    import tempfile
    old_path = nb.DEFAULT_QUOTE_POOL
    with tempfile.TemporaryDirectory() as td:
        nb.DEFAULT_QUOTE_POOL = os.path.join(td, "原话池.md")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                fb = nb.load_quote_pool()
        finally:
            nb.DEFAULT_QUOTE_POOL = old_path
    out = buf.getvalue()
    check("缺池子仍能玩（三张内置）", len(fb.active()) == 3 and fb.version == "内置")
    check("缺池子会明说", "没找到 原话池.md" in out and "v0.5" in out)

    a = [q["id"] for q in p.select(3)]
    b = [q["id"] for q in p.select(3)]
    check("同 seed 抽同一组", a == b)
    check("抽 3 条且不重复", len(a) == 3 and len(set(a)) == 3)
    tags_ok = True
    for s in range(200):
        tags = {q.get("to") for q in p.select(s)}
        if not ({"self", "other"} <= tags):
            tags_ok = False
            break
    check("每局至少一张 self/other", tags_ok)
    c = [q["id"] for q in p.select(4)]
    check("不同 seed 可抽不同组", a != c)

    g = nb.Notebook(seed=1)
    g.pos = (1, 0)
    g.hidden = {(1, 0): "某句"}
    g.hidden_ids = {(1, 0): "q07"}
    quiet(g.copy)
    check("抄写记下原话 id", g.piece_ids == ["q07"])

    d = tmpdir("pool_retired")
    pp = os.path.join(d, "pool.md")
    with open(pp, "w", encoding="utf-8") as f:
        f.write("pool: test-pool\nstatus: active\n\n"
                "## q01\n一\n## q02\n二\n## q03 retired\n三\n## q04\n四\n")
    p2 = nb.load_quote_pool(pp)
    check("retired 不参与抽取", [x["id"] for x in p2.active()] == ["q01", "q02", "q04"])

    ph = os.path.join(d, "placeholder.md")
    with open(ph, "w", encoding="utf-8") as f:
        f.write("pool: ph\nstatus: placeholder\n\n"
                "## q01\n###原话-01###\n## q02\n二\n## q03\n三\n")
    ph_pool = nb.load_quote_pool(ph)
    try:
        nb.Notebook(seed=1, quote_pool=ph_pool, strict_content=True)
        strict_ok = False
    except ValueError:
        strict_ok = True
    check("strict-content 拒绝占位池", strict_ok)
    check("strict-content 接受真实池",
          nb.Notebook(seed=1, strict_content=True).quote_pool.status == "active")

    pp2 = os.path.join(d, "bad.md")
    with open(pp2, "w", encoding="utf-8") as f:
        f.write("pool: bad\nstatus: active\n\n## q01\n###原话-01###\n")
    try:
        nb.load_quote_pool(pp2)
        bad_ok = False
    except ValueError:
        bad_ok = True
    check("active 池里出现占位格会报错", bad_ok)

    try:
        nb.load_quote_pool(os.path.join(d, "missing.md"))
        missing_ok = False
    except ValueError:
        missing_ok = True
    check("显式 --pool 指错会报错", missing_ok)

    r = subprocess.run([sys.executable, NOTEBOOK, "--strict-content"],
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONUTF8="1"))
    check("CLI strict 真实池退出 0", r.returncode == 0)
    r2 = subprocess.run([sys.executable, NOTEBOOK, "--strict-content", "--pool", ph],
                        capture_output=True, text=True, encoding="utf-8",
                        env=dict(os.environ, PYTHONUTF8="1"))
    check("CLI strict 占位池退出 2", r2.returncode == 2)
    check("CLI strict 说清原因", "占位" in (r2.stdout + r2.stderr))

    e = nb.make_entry(3, "B", nb.TITLES["B"], "一句原话", "留话", "甲",
                      pool="原话池-v1", quote_ids="q01,q03")
    store = nb.ReceiptStore(os.path.join(d, "r.md"))
    txt = store._format(e)
    check("回执写原话池", "- 原话池：原话池-v1" in txt)
    check("回执写三张 id", "- 原话 id：q01,q03" in txt)
    back = nb.ReceiptStore._parse_block(txt.splitlines())
    check("回执解析 pool", back and back.get("pool") == "原话池-v1")
    check("回执解析 id", back and back.get("quote_ids") == "q01,q03")


def test_inbox():
    group("跨机器门缝")
    d = tmpdir("inbox")
    s = nb.InboxStore(d, name="甲")
    check("空目录没有留话", s.latest_line() is None)
    check("第一次写成功", s.append("第一句"))
    check("第二次写成功", s.append("第二句"))
    check("一人一次一份文件", len(s._files()) == 2)
    latest = s.latest_line()
    check("读最近一条", latest == "第二句")
    check("读状态记在 .read/甲.json",
          os.path.exists(os.path.join(d, ".read", "甲.json")))
    read = open(os.path.join(d, ".read", "甲.json"), encoding="utf-8").read()
    last_name = json.loads(read)["last"]
    check("读状态记的是刚读的文件", last_name in s._files())
    check("读状态对应的文件确是最新", "第二句" in open(
        os.path.join(d, last_name), encoding="utf-8").read())

    # 文件头时间优先于文件名日期（单独目录，避免被刚才的 append 抢走）
    d_head = tmpdir("inbox_head")
    s_head = nb.InboxStore(d_head, name="甲")
    with open(os.path.join(d_head, "2030-01-01-乙-0001.md"), "w", encoding="utf-8") as f:
        f.write("<!-- t: 2020-01-01T10:00:00+08:00 -->\n\n旧头\n第二行\n")
    with open(os.path.join(d_head, "2025-01-01-丙-0002.md"), "w", encoding="utf-8") as f:
        f.write("<!-- t: 2026-01-01T10:00:00+08:00 -->\n\n新头\n第二行\n")
    check("文件头时间优先于文件名", s_head.latest_line() == "新头")

    # 没有文件头时退回文件名日期
    with open(os.path.join(d_head, "2031-01-01-丁-0003.md"), "w", encoding="utf-8") as f:
        f.write("\n文件名日期\n")
    check("没有头按文件名日期", s_head.latest_line() == "文件名日期")
    check("文件名日期不算时间未知", s_head.time_unknown is False)

    # 头和文件名都没有，才退回 mtime，并标记时间未知（单独目录）
    d_mtime = tmpdir("inbox_mtime")
    s_mtime = nb.InboxStore(d_mtime, name="甲")
    p = os.path.join(d_mtime, "nohint.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("只有正文\n")
    os.utime(p, (946684800, 946684800))
    check("最后才退回 mtime", s_mtime.latest_line() == "只有正文")
    check("mtime 兜底标时间未知", s_mtime.time_unknown is True)

    # 署名清洗、不覆盖
    d2 = tmpdir("inbox_name")
    s2 = nb.InboxStore(d2, name="a/b:c")
    check("署名清洗后能写", s2.append("一句"))
    check("文件名不含斜杠", all("/" not in x and ":" not in x for x in s2._files()))
    check("署名清洗成 a_b_c", any("a_b_c" in x for x in s2._files()))

    # 回声从 inbox 取最近一条，不经过 DoorStore
    d_echo = tmpdir("inbox_echo")
    s_echo = nb.InboxStore(d_echo, name="甲")
    s_echo.append("门缝里的一句")
    g = nb.Notebook(seed=3, door=s_echo, echo="always", fold=False)
    for _ in range(g.echo_wake - 1):
        g.next_round()
    check("回声页来自 inbox", any(p["text"] == "门缝里的一句" for p in g.pages))

    # CLI 接线
    rp = os.path.join(d, "r.md")
    class Dummy:
        def __init__(self, **kw):
            Dummy.last = kw
        def play(self):
            pass
    old = nb.Notebook
    try:
        nb.Notebook = Dummy
        nb.main(["--receipt", rp, "--inbox", d, "--name", "甲"])
        check("--inbox 用 InboxStore", isinstance(Dummy.last["door"], nb.InboxStore))
        check("--inbox 传署名", Dummy.last["door"].name == "甲")
        nb.main(["--no-receipt", "--inbox", d])
        check("--no-receipt 连 inbox 一起关", Dummy.last["door"] is None)
    finally:
        nb.Notebook = old


def test_http_door():
    group("HTTP 门缝")

    # ── 桩服务器 ─────────────────────────────────────────
    class _Stub(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # 安静
            pass
        def do_GET(self):
            if "?list=" in self.path:
                body = json.dumps({"items": [
                    {"line": "旧", "ts": 1}, {"line": "新", "ts": 2}
                ], "count": 2}).encode()
            elif self.path.endswith("/door"):
                body = json.dumps({"line": "你好", "ts": 1}).encode()
            else:
                body = json.dumps({"line": None, "ts": None}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            try:
                data = json.loads(body)
            except Exception:
                data = {}
            line = data.get("line", "")
            if line == "error":
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "ts": 999}).encode())

    srv = http.server.HTTPServer(("127.0.0.1", 0), _Stub)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    try:
        # 1. GET 拿到 {"line": "你好"} → latest_line() == "你好"
        d = nb.HttpDoorStore(f"http://127.0.0.1:{port}")
        check("GET 有 line", d.latest_line() == "你好")

        # 2. GET 空 line → None
        d2 = nb.HttpDoorStore(f"http://127.0.0.1:{port}")
        d2.path = d2.path.replace("/door", "/door2")  # 桩里 /door2 回空
        check("GET 空 line → None", d2.latest_line() is None)

        # 3. GET 500 → None 且不抛
        class _Bad(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                self.send_response(500); self.end_headers()
        srv2 = http.server.HTTPServer(("127.0.0.1", 0), _Bad)
        p2 = srv2.server_address[1]
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        d3 = nb.HttpDoorStore(f"http://127.0.0.1:{p2}")
        check("GET 500 → None", d3.latest_line() is None)

        # 4. POST 成功 → True；POST 500 → False 且不抛
        d4 = nb.HttpDoorStore(f"http://127.0.0.1:{port}")
        check("POST 成功", d4.append("塞一句") is True)
        d5 = nb.HttpDoorStore(f"http://127.0.0.1:{p2}")
        check("POST 500 → False", d5.append("error") is False)

        # 5. list_recent 正常
        d6 = nb.HttpDoorStore(f"http://127.0.0.1:{port}")
        r = d6.list_recent(10)
        check("list_recent 有条数", r is not None and r["count"] == 2)
        check("list_recent 有 items", r is not None and len(r["items"]) == 2)

        # 6. 连不上 → None/False 且不抛
        d7 = nb.HttpDoorStore("http://127.0.0.1:1")  # 端口 1 必挂
        check("连不上 latest_line → None", d7.latest_line() is None)
        check("连不上 append → False", d7.append("x") is False)
        check("连不上 list_recent → None", d7.list_recent(10) is None)
    finally:
        srv.shutdown()
        srv2.shutdown()


def main():
    print("本子 自动化测试\n")
    test_api()
    test_endings()
    test_e2e()
    test_balance()
    test_receipt_format()
    test_finish_receipt()
    test_echo_page()
    test_door_slot()
    test_cli()
    test_fold()
    test_unlocated()
    test_clock_and_fields()
    test_door_v05()
    test_v05_cli()
    test_quote_pool()
    test_inbox()
    test_http_door()
    print()
    for title, total, passed in GROUPS:
        print(f"  {title}：{passed}/{total}")
    if FAILS:
        print(f"\n失败 {len(FAILS)} 项：{'、'.join(FAILS)}")
        sys.exit(1)
    print("\n全部通过。")
    sys.exit(0)


if __name__ == "__main__":
    main()
