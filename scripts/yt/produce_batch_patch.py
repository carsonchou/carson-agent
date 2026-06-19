#!/usr/bin/env python3
# 在伺服器上執行：修補 produce_batch.py 兩處邏輯
import sys
from pathlib import Path

TARGET = Path("/root/yt/scripts/produce_batch.py")

if not TARGET.exists():
    print(f"[FATAL] 找不到 {TARGET}", file=sys.stderr)
    sys.exit(1)

src = TARGET.read_text(encoding="utf-8")
original = src

# ─── Patch 1: existing_titles() 加入 ledger 讀取 ───
OLD1 = '''def existing_titles():
    out = []
    for f in OUT.glob("*.md"):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            out.append(first.replace("# \U0001f3ac", "").strip())
        except Exception:
            pass
    return out'''

NEW1 = '''def existing_titles():
    out = []
    for f in OUT.glob("*.md"):
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0]
            out.append(first.replace("# \U0001f3ac", "").strip())
        except Exception:
            pass
    # 從已上架 ledger 讀標題，防止每日重複生成近似題材
    ledger_path = ROOT / "STUDIO" / "uploaded_ledger.json"
    if ledger_path.exists():
        try:
            import re as _re
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            for slug_key in ledger:
                title = _re.sub(r\'^[SL]_\', \'\', slug_key)
                if title:
                    out.append(title)
        except Exception:
            pass
    return out'''

if OLD1 in src:
    src = src.replace(OLD1, NEW1, 1)
    print("[OK] Patch 1 applied: existing_titles() 加入 ledger 讀取")
else:
    print("[WARN] Patch 1 未找到精確匹配，嘗試寬鬆比對...")
    # 寬鬆：找到函數結尾 return out 之前插入
    import re
    m = re.search(
        r'(def existing_titles\(\):.*?)(    return out)',
        src, re.S
    )
    if m:
        insert = '''    # 從已上架 ledger 讀標題，防止每日重複生成近似題材
    ledger_path = ROOT / "STUDIO" / "uploaded_ledger.json"
    if ledger_path.exists():
        try:
            import re as _re
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            for slug_key in ledger:
                title = _re.sub(r\'^[SL]_\', \'\', slug_key)
                if title:
                    out.append(title)
        except Exception:
            pass
    '''
        src = src[:m.start(2)] + insert + src[m.start(2):]
        print("[OK] Patch 1 寬鬆插入成功")
    else:
        print("[FAIL] Patch 1 失敗，找不到 existing_titles", file=sys.stderr)

# ─── Patch 2: make_one() 品管閘門 ───
OLD2 = '''    if ok:  # 產製即審核：壞片/違規早發現
        passed, reasons = audit_video.audit(slug)
        if not passed:
            log_ops("補產·審核", f"⚠️ {slug} 審核未過：{\'；\'.join(reasons)[:60]}")
    print(f"[{\'ok\' if ok else \'FAIL\'}] {kind} {slug}")
    return slug if ok else None'''

NEW2 = '''    if ok:  # 產製即審核：壞片/違規早發現
        passed, reasons = audit_video.audit(slug)
        if not passed:
            log_ops("補產·審核", f"⚠️ {slug} 審核未過：{\'；\'.join(reasons)[:60]}")
            _FATAL = ("片長過短", "無視訊軌", "無音軌", "檔案過小")
            if any(any(tag in r for tag in _FATAL) for r in reasons):
                try:
                    (OUT / f"{slug}.mp4").unlink(missing_ok=True)
                except Exception:
                    pass
                log_ops("補產·品管", f"結構性壞片已丟棄：{slug}")
                ok = False
    print(f"[{\'ok\' if ok else \'FAIL\'}] {kind} {slug}")
    return slug if ok else None'''

if OLD2 in src:
    src = src.replace(OLD2, NEW2, 1)
    print("[OK] Patch 2 applied: 品管閘門補強（壞片自動丟棄）")
else:
    print("[WARN] Patch 2 未找到精確匹配，嘗試寬鬆比對...")
    import re
    m = re.search(
        r'(    if ok:  # 產製即審核.*?)(    print\(f"\[)',
        src, re.S
    )
    if m:
        old_block = m.group(0)
        audit_section = m.group(1)
        # 在 audit 區塊內 if not passed: 後加入品管邏輯
        if 'if not passed:' in audit_section:
            new_audit = audit_section.replace(
                '            log_ops("補產·審核", f"⚠️ {slug} 審核未過：{\'；\'.join(reasons)[:60]}")\n',
                '            log_ops("補產·審核", f"⚠️ {slug} 審核未過：{\'；\'.join(reasons)[:60]}")\n'
                '            _FATAL = ("片長過短", "無視訊軌", "無音軌", "檔案過小")\n'
                '            if any(any(tag in r for tag in _FATAL) for r in reasons):\n'
                '                try:\n'
                '                    (OUT / f"{slug}.mp4").unlink(missing_ok=True)\n'
                '                except Exception:\n'
                '                    pass\n'
                '                log_ops("補產·品管", f"結構性壞片已丟棄：{slug}")\n'
                '                ok = False\n'
            )
            src = src[:m.start()] + new_audit + src[m.start(2):]
            print("[OK] Patch 2 寬鬆插入成功")
        else:
            print("[FAIL] Patch 2 找不到 if not passed:", file=sys.stderr)
    else:
        print("[FAIL] Patch 2 失敗，找不到品管位置", file=sys.stderr)

if src != original:
    TARGET.write_text(src, encoding="utf-8")
    print(f"[OK] {TARGET} 已更新")
else:
    print("[WARN] 未做任何修改")
