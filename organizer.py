#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
file_organizer.py — консольная утилита для наведения порядка в папках.

Команды:
    sort      разложить файлы по подпапкам (по типам, датам или расширениям)
    rename    пакетное переименование по шаблону ({name}, {num}, {date}, {ext}...)
    dupes     найти дубликаты файлов по содержимому (SHA-256), без сканирования вручную
    report    отчёт: чем занята папка (топ-категории, крупные файлы, старьё)

Примеры:
    python organizer.py sort "D:\\Загрузки" --by type
    python organizer.py sort "D:\\Фото" --by date --dry-run
    python organizer.py rename "D:\\скан\\*" --pattern "{date}_{num}{ext}" --start 1
    python organizer.py dupes "D:\\фото" --delete
    python organizer.py report "D:\\Загрузки"
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CHUNK = 1024 * 1024

# категории для --by type
CATEGORY = {
    ".jpg": "Изображения", ".jpeg": "Изображения", ".png": "Изображения",
    ".gif": "Изображения", ".webp": "Изображения", ".svg": "Изображения",
    ".pdf": "Документы", ".doc": "Документы", ".docx": "Документы",
    ".xls": "Таблицы", ".xlsx": "Таблицы", ".csv": "Таблицы",
    ".txt": "Текст", ".md": "Текст", ".rtf": "Документы",
    ".mp3": "Аудио", ".wav": "Аудио", ".flac": "Аудио",
    ".mp4": "Видео", ".mkv": "Видео", ".avi": "Видео", ".mov": "Видео",
    ".zip": "Архивы", ".rar": "Архивы", ".7z": "Архивы",
    ".exe": "Программы", ".msi": "Программы",
    ".dxf": "Чертежи", ".dwg": "Чертежи",
}
OTHER = "Прочее"


def human(n: float) -> str:
    for u in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or u == "ТБ":
            return f"{n:.1f} {u}" if u != "Б" else f"{int(n)} {u}"
        n /= 1024
    return f"{n:.1f} ТБ"


def walk(folder: Path, recursive: bool):
    it = folder.rglob("*") if recursive else folder.glob("*")
    for p in it:
        if p.is_file():
            yield p


# ──────────────────────────────────────────────────────────── sort ──
def cmd_sort(args) -> None:
    folder = Path(args.folder)
    if not folder.is_dir():
        raise SystemExit(f"Папка не найдена: {folder}")
    moves: list[tuple[Path, Path]] = []
    for p in walk(folder, args.recursive):
        if p.parent == folder and p.name == "organizer.py":
            continue
        if args.by == "type":
            sub = CATEGORY.get(p.suffix.lower(), OTHER)
        elif args.by == "ext":
            sub = (p.suffix or "без_расширения").lstrip(".").lower() or "без_расширения"
        else:  # date
            sub = time.strftime("%Y-%m", time.localtime(p.stat().st_mtime))
        dest_dir = folder / sub
        dest = dest_dir / p.name
        n = 1
        while dest.exists():
            dest = dest_dir / f"{p.stem} ({n}){p.suffix}"
            n += 1
        moves.append((p, dest))

    if not moves:
        print("Нечего перемещать — файлы уже разложены.")
        return
    for src, dest in moves:
        print(f"{src.name:50s} -> {dest.parent.name}\\")
        if args.dry_run:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}перемещено файлов: {len(moves)}")


# ────────────────────────────────────────────────────────── rename ──
def cmd_rename(args) -> None:
    folder = Path(args.folder)
    if not folder.is_dir():
        raise SystemExit(f"Папка не найдена: {folder}")
    files = sorted(f for f in walk(folder, False) if not f.name.startswith("."))
    start = args.start
    today = datetime.now().strftime("%Y-%m-%d")
    width = max(2, len(str(start + len(files))))  # 01, 02...
    renames: list[tuple[Path, Path]] = []
    for i, p in enumerate(files):
        num = str(start + i).zfill(width)
        new_name = args.pattern.format(
            num=num, name=re.sub(r"[^\w\- ]", "", p.stem).strip(), date=today,
            ext=p.suffix.lower(), mtime=time.strftime(
                "%Y-%m-%d", time.localtime(p.stat().st_mtime)),
        ) + ("" if "{ext}" in args.pattern else p.suffix.lower())
        if "{" in new_name:
            raise SystemExit(f"Неизвестное поле в шаблоне: {new_name}")
        renames.append((p, folder / new_name))
    for src, dest in renames:
        if src == dest:
            continue
        print(f"{src.name:50s} -> {dest.name}")
        if args.dry_run:
            continue
        if dest.exists():
            raise SystemExit(f"Конфликт: {dest} уже существует")
        src.rename(dest)
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}переименовано: "
          f"{sum(1 for s, d in renames if s != d)} из {len(files)}")


# ──────────────────────────────────────────────────────────── dupes ──
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_dupes(args) -> None:
    folder = Path(args.folder)
    if not folder.is_dir():
        raise SystemExit(f"Папка не найдена: {folder}")
    print("Сканирую (сперва по размеру, затем по SHA-256)...")
    by_size: dict[int, list[Path]] = defaultdict(list)
    for p in walk(folder, True):
        by_size[p.stat().st_size].append(p)

    groups: dict[str, list[Path]] = defaultdict(list)
    for size, paths in by_size.items():
        if len(paths) < 2 or size == 0:
            continue
        for p in paths:
            groups[sha256(p)].append(p)

    dupes = {h: ps for h, ps in groups.items() if len(ps) > 1}
    if not dupes:
        print("Дубликатов не найдено.")
        return
    freed = 0
    for h, ps in sorted(dupes.items(), key=lambda x: -x[1][0].stat().st_size):
        size = ps[0].stat().st_size
        freed += size * (len(ps) - 1)
        print(f"\n{len(ps)} копии по {human(size)}:")
        keep = ps[0]
        print(f"  ОСТАВИТЬ: {keep}")
        for p in ps[1:]:
            print(f"  дубликат: {p}")
            if args.delete:
                p.unlink()
    print(f"\n{'[DRY RUN] ' if not args.delete else ''}можно освободить: {human(freed)}")


# ─────────────────────────────────────────────────────────── report ──
def cmd_report(args) -> None:
    folder = Path(args.folder)
    if not folder.is_dir():
        raise SystemExit(f"Папка не найдена: {folder}")
    cats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    all_files = list(walk(folder, args.recursive))
    if not all_files:
        print("Папка пуста.")
        return
    for p in all_files:
        st = p.stat()
        c = cats[CATEGORY.get(p.suffix.lower(), OTHER)]
        c[0] += 1
        c[1] += st.st_size
    total = sum(v[1] for v in cats.values())
    print(f"Папка: {folder.resolve()}")
    print(f"Файлов: {len(all_files)}, суммарно {human(total)}\n")
    print(f"{'Категория':<14}{'файлов':>8}{'размер':>12}")
    for cat, (n, s) in sorted(cats.items(), key=lambda x: -x[1][1]):
        print(f"{cat:<14}{n:>8}{human(s):>12}  {'█' * int(40 * s / total)}")
    print("\nТоп-5 крупных файлов:")
    for p in sorted(all_files, key=lambda x: -x.stat().st_size)[:5]:
        print(f"  {human(p.stat().st_size):>10}  {p.relative_to(folder)}")
    cutoff = time.time() - 365 * 86400
    old = [p for p in all_files if p.stat().st_mtime < cutoff]
    if old:
        print(f"\nНе трогали больше года: {len(old)} файл(ов), "
              f"{human(sum(p.stat().st_size for p in old))} — кандидаты в архив")


def main() -> None:
    ap = argparse.ArgumentParser(prog="organizer", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sort", help="разложить файлы по подпапкам")
    sp.add_argument("folder")
    sp.add_argument("--by", choices=("type", "ext", "date"), default="type")
    sp.add_argument("-r", "--recursive", action="store_true")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_sort)

    rp = sub.add_parser("rename", help="пакетное переименование")
    rp.add_argument("folder")
    rp.add_argument("--pattern", required=True,
                    help="шаблон: {num}, {name}, {date}, {mtime}, {ext}")
    rp.add_argument("--start", type=int, default=1)
    rp.add_argument("--dry-run", action="store_true")
    rp.set_defaults(func=cmd_rename)

    dp = sub.add_parser("dupes", help="найти дубликаты по содержимому")
    dp.add_argument("folder")
    dp.add_argument("--delete", action="store_true")
    dp.set_defaults(func=cmd_dupes)

    xp = sub.add_parser("report", help="отчёт по папке")
    xp.add_argument("folder")
    xp.add_argument("-r", "--recursive", action="store_true")
    xp.set_defaults(func=cmd_report)

    args = ap.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
