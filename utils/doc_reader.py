"""
Eski ikkilik Word (.doc, Word 97-2003) fayllaridan MATN ajratish — faqat sof Python,
tashqi dastur (LibreOffice/antiword) va qo'shimcha kutubxona (olefile) KERAK EMAS.

Nega kerak: docx2txt va mammoth faqat .docx (zip) ni o'qiydi; haqiqiy .doc (OLE2/CFB)
ularda "o'qilmadi" xatosini beradi. Bu modul:
  1. OLE2 (Compound File) konteynerini o'qiydi (FAT/miniFAT zanjirlari),
  2. "WordDocument" oqimidagi FIB va "0Table"/"1Table" dagi CLX (piece table) dan matn bo'laklarini
     (8-bit cp1252 yoki UTF-16) yig'adi,
  3. paragraf/jadval belgilarini yangi qatorga aylantiradi, maydon kodlarini (HYPERLINK ...) tashlaydi.
Rasmlar o'qilmaydi (faqat matn). Shifrlangan fayllar qo'llab-quvvatlanmaydi.
"""
import re
import struct

_FREESECT, _ENDOFCHAIN, _FATSECT, _DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
_MAX_SECTORS = 1 << 22


class DocError(Exception):
    pass


class _CFB:
    def __init__(self, data: bytes):
        if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise DocError("OLE2 emas")
        self.d = data
        self.ss = 1 << struct.unpack_from("<H", data, 0x1E)[0]
        self.mss = 1 << struct.unpack_from("<H", data, 0x20)[0]
        n_fat, first_dir, _, cutoff, first_mfat, n_mfat, first_dif, n_dif = struct.unpack_from(
            "<IIIIIIII", data, 0x2C)
        self.cutoff = cutoff or 4096
        difat = list(struct.unpack_from("<109I", data, 0x4C))
        s = first_dif
        for _ in range(n_dif):
            if s >= _DIFSECT:
                break
            sec = self._sector(s)
            vals = struct.unpack("<%dI" % (self.ss // 4), sec)
            difat += list(vals[:-1])
            s = vals[-1]
        fat = []
        for s in difat[:n_fat] if n_fat else difat:
            if s >= _DIFSECT:
                continue
            fat += struct.unpack("<%dI" % (self.ss // 4), self._sector(s))
        self.fat = fat
        self.entries = self._read_dir(first_dir)
        root = self.entries[0]
        self.ministream = self._chain(root["start"]) if root["start"] < _DIFSECT else b""
        self.minifat = []
        if n_mfat and first_mfat < _DIFSECT:
            mf = self._chain(first_mfat)
            self.minifat = list(struct.unpack("<%dI" % (len(mf) // 4), mf[: len(mf) // 4 * 4]))

    def _sector(self, i: int) -> bytes:
        off = (i + 1) * self.ss
        sec = self.d[off: off + self.ss]
        if len(sec) < self.ss:
            sec = sec + b"\x00" * (self.ss - len(sec))
        return sec

    def _chain(self, start: int) -> bytes:
        out, seen, s = [], 0, start
        while s < _DIFSECT and seen < _MAX_SECTORS:
            if s >= len(self.fat):
                break
            out.append(self._sector(s))
            s = self.fat[s]
            seen += 1
        return b"".join(out)

    def _read_dir(self, first: int) -> list:
        raw = self._chain(first)
        res = []
        for i in range(0, len(raw) - 127, 128):
            e = raw[i: i + 128]
            nlen = struct.unpack_from("<H", e, 0x40)[0]
            name = e[: max(nlen - 2, 0)].decode("utf-16le", "ignore")
            typ = e[0x42]
            start = struct.unpack_from("<I", e, 0x74)[0]
            size = struct.unpack_from("<Q", e, 0x78)[0] & 0xFFFFFFFF
            res.append({"name": name, "type": typ, "start": start, "size": size})
        return res

    def stream(self, name: str) -> bytes:
        for e in self.entries:
            if e["type"] == 2 and e["name"] == name:
                if e["size"] < self.cutoff:
                    out, s, seen = [], e["start"], 0
                    while s < _DIFSECT and s < len(self.minifat) and seen < _MAX_SECTORS:
                        out.append(self.ministream[s * self.mss:(s + 1) * self.mss])
                        s = self.minifat[s]
                        seen += 1
                    return b"".join(out)[: e["size"]]
                return self._chain(e["start"])[: e["size"]]
        raise DocError(f"oqim topilmadi: {name}")


def _clean(text: str) -> str:
    # Maydon kodlari: \x13 KOD \x14 NATIJA \x15  → faqat NATIJA qoladi
    out, depth_skip, stack = [], 0, []
    for ch in text:
        if ch == "\x13":
            stack.append(False)          # hozircha kod qismi
        elif ch == "\x14":
            if stack:
                stack[-1] = True         # natija boshlandi
        elif ch == "\x15":
            if stack:
                stack.pop()
        else:
            if stack and not stack[-1]:
                continue                 # maydon kodi ichida
            out.append(ch)
    t = "".join(out)
    t = t.replace("\r\x07", "\n").replace("\x07", "\n").replace("\r", "\n")
    t = t.replace("\x0b", "\n").replace("\x0c", "\n").replace("\xa0", " ")
    t = re.sub(r"[\x00-\x08\x0e-\x1f\x7f]", "", t)
    return t


def extract_doc_text(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    cfb = _CFB(data)
    wd = cfb.stream("WordDocument")
    if len(wd) < 0x200 or struct.unpack_from("<H", wd, 0)[0] != 0xA5EC:
        raise DocError("Word FIB emas")
    flags = struct.unpack_from("<H", wd, 0x0A)[0]
    if flags & 0x0100:
        raise DocError("shifrlangan .doc")
    tbl = cfb.stream("1Table" if flags & 0x0200 else "0Table")

    pos = 0x20
    csw = struct.unpack_from("<H", wd, pos)[0]
    pos += 2 + csw * 2
    cslw = struct.unpack_from("<H", wd, pos)[0]
    lw_off = pos + 2
    ccp_text = struct.unpack_from("<i", wd, lw_off + 3 * 4)[0]       # asosiy matn uzunligi (CP)
    pos = lw_off + cslw * 4
    cb = struct.unpack_from("<H", wd, pos)[0]
    blob = pos + 2
    if cb < 34:
        raise DocError("FIB qisqa")
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, blob + 33 * 8)
    clx = tbl[fc_clx: fc_clx + lcb_clx]

    i = 0
    while i < len(clx) and clx[i] == 0x01:                           # Prc — o'tkazib yuboramiz
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise DocError("piece table topilmadi")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5: i + 5 + lcb]
    n = (len(plc) - 4) // 12
    if n <= 0:
        raise DocError("piece table bo'sh")
    cps = struct.unpack_from("<%dI" % (n + 1), plc, 0)
    parts, total = [], 0
    for k in range(n):
        cp0, cp1 = cps[k], cps[k + 1]
        if ccp_text > 0:
            if cp0 >= ccp_text:
                break
            cp1 = min(cp1, ccp_text)
        cnt = max(cp1 - cp0, 0)
        fc = struct.unpack_from("<I", plc, (n + 1) * 4 + k * 8 + 2)[0]
        if fc & 0x40000000:                                          # siqilgan: 8-bit
            off = (fc & 0x3FFFFFFF) // 2
            parts.append(wd[off: off + cnt].decode("cp1252", "replace"))
        else:
            off = fc & 0x3FFFFFFF
            parts.append(wd[off: off + cnt * 2].decode("utf-16le", "replace"))
        total += cnt
    text = _clean("".join(parts))
    if not text.strip():
        raise DocError("matn bo'sh")
    return text
