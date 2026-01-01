"""University background lookup (QS/211/985) for Vercel runtime.

Vercel Python runtime for this project does not include pandas/openpyxl, so we
parse the XLSX (Office Open XML zip) directly.
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional
from xml.etree import ElementTree as ET


_QS_XLSX_FILENAME = "2026_qs_world_university_rankings.xlsx"
_DEFAULT_XLSX = Path(__file__).resolve().parent / _QS_XLSX_FILENAME


def _default_xlsx_path() -> Path:
    env = (os.getenv("QS_2026_XLSX_PATH") or "").strip()
    if env:
        return Path(env).expanduser()
    return _DEFAULT_XLSX


def _norm_zh(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def _norm_en(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("&", "and")
    s = re.sub(r"[^a-z0-9 \-\.]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_rank(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


@dataclass(frozen=True)
class UniversityLookupResult:
    qs_rank: Optional[int]
    is_211: bool
    is_985: bool
    matched_name_en: Optional[str]
    matched_name_zh: Optional[str]
    matched_by: Optional[str]  # "zh" | "en" | None

    def model_dump(self) -> dict[str, Any]:
        return {
            "qs_rank": self.qs_rank,
            "is_211": self.is_211,
            "is_985": self.is_985,
            "matched_name_en": self.matched_name_en,
            "matched_name_zh": self.matched_name_zh,
            "matched_by": self.matched_by,
        }


def _xlsx_sheet_name_to_path(zf: zipfile.ZipFile) -> dict[str, str]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    sheet_id_to_name: dict[str, str] = {}
    for sheet in workbook.findall(".//m:sheets/m:sheet", ns):
        name = sheet.attrib.get("name", "")
        rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
        if name and rid:
            sheet_id_to_name[rid] = name

    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target: dict[str, str] = {}
    for rel in rels.findall(".//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        rid = rel.attrib.get("Id", "")
        target = rel.attrib.get("Target", "")
        if rid and target:
            rid_to_target[rid] = target

    out: dict[str, str] = {}
    for rid, name in sheet_id_to_name.items():
        target = rid_to_target.get(rid, "")
        if not target:
            continue
        if target.startswith("/"):
            target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        out[name] = target
    return out


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in zf.namelist():
        return []
    root = ET.fromstring(zf.read(path))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    out: list[str] = []
    for si in root.findall(".//m:si", ns):
        parts = [t.text or "" for t in si.findall(".//m:t", ns)]
        out.append("".join(parts))
    return out


def _cell_col_letter(cell_ref: str) -> str:
    m = re.match(r"^([A-Z]+)\d+$", cell_ref or "")
    return m.group(1) if m else ""


def _xlsx_read_sheet_columns(
    xlsx_path: Path,
    sheet_name: str,
    col_letters: Iterable[str],
) -> list[dict[str, Any]]:
    cols = {c.upper() for c in col_letters}
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        sheet_map = _xlsx_sheet_name_to_path(zf)
        sheet_path = sheet_map.get(sheet_name)
        if not sheet_path:
            raise KeyError(f"Sheet '{sheet_name}' not found in: {xlsx_path}")
        shared = _xlsx_shared_strings(zf)

        root = ET.fromstring(zf.read(sheet_path))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows: list[dict[str, Any]] = []
        for row in root.findall(".//m:sheetData/m:row", ns):
            row_map: dict[str, Any] = {}
            for c in row.findall("m:c", ns):
                ref = c.attrib.get("r", "")
                col = _cell_col_letter(ref)
                if col not in cols:
                    continue
                cell_type = c.attrib.get("t", "")
                v = c.find("m:v", ns)
                if v is None or v.text is None:
                    continue
                raw = v.text
                if cell_type == "s":
                    try:
                        idx = int(raw)
                        row_map[col] = shared[idx] if 0 <= idx < len(shared) else ""
                    except Exception:
                        row_map[col] = ""
                else:
                    row_map[col] = raw
            if row_map:
                rows.append(row_map)
        return rows


@lru_cache(maxsize=1)
def _load_university_lists_from_xlsx(xlsx_path: str) -> dict[str, Any]:
    path = Path(xlsx_path)
    if not path.exists():
        raise FileNotFoundError(f"QS rankings file not found: {path}")

    rows = _xlsx_read_sheet_columns(path, "QS", ["A", "C", "D"])
    list_211 = [r.get("A") for r in _xlsx_read_sheet_columns(path, "211", ["A"]) if r.get("A")]
    list_985 = [r.get("A") for r in _xlsx_read_sheet_columns(path, "985", ["A"]) if r.get("A")]

    qs_by_zh: dict[str, tuple[int, str, str]] = {}
    qs_by_en: dict[str, tuple[int, str, str]] = {}

    for r in rows:
        rank = _parse_rank(r.get("A"))
        en = (r.get("C") or "").strip()
        zh = (r.get("D") or "").strip()
        if not rank or (not en and not zh):
            continue
        if zh:
            qs_by_zh[_norm_zh(zh)] = (rank, en, zh)
        if en:
            qs_by_en[_norm_en(en)] = (rank, en, zh)

    set_211 = {_norm_zh(str(x)) for x in list_211 if str(x).strip()}
    set_985 = {_norm_zh(str(x)) for x in list_985 if str(x).strip()}

    return {
        "qs_by_zh": qs_by_zh,
        "qs_by_en": qs_by_en,
        "set_211": set_211,
        "set_985": set_985,
    }


def lookup_university_background(
    *,
    school_name_en: Optional[str] = None,
    school_name_zh: Optional[str] = None,
    xlsx_path: Path | str | None = None,
) -> UniversityLookupResult:
    path = Path(xlsx_path) if xlsx_path is not None else _default_xlsx_path()
    data = _load_university_lists_from_xlsx(str(path))

    qs_rank: Optional[int] = None
    matched_en: Optional[str] = None
    matched_zh: Optional[str] = None
    matched_by: Optional[str] = None

    is_211 = False
    is_985 = False

    zh_norm = _norm_zh(school_name_zh or "")
    if zh_norm:
        hit = data["qs_by_zh"].get(zh_norm)
        if hit:
            qs_rank, matched_en, matched_zh = hit
            matched_by = "zh"
        is_211 = zh_norm in data["set_211"]
        is_985 = zh_norm in data["set_985"]

    if qs_rank is None:
        en_norm = _norm_en(school_name_en or "")
        if en_norm:
            hit = data["qs_by_en"].get(en_norm)
            if hit:
                qs_rank, matched_en, matched_zh = hit
                matched_by = "en"
                if matched_zh:
                    matched_zh_norm = _norm_zh(matched_zh)
                    if matched_zh_norm:
                        is_211 = matched_zh_norm in data["set_211"]
                        is_985 = matched_zh_norm in data["set_985"]

    return UniversityLookupResult(
        qs_rank=qs_rank,
        is_211=bool(is_211),
        is_985=bool(is_985),
        matched_name_en=matched_en,
        matched_name_zh=matched_zh,
        matched_by=matched_by,
    )

