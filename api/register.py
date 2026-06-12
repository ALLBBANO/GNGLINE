# -*- coding: utf-8 -*-
"""
GSV → 지파넷 등록 API (Vercel 서버리스 함수)
- mode=verify : 로그인 확인 + 사용자 정보 반환 (비번은 응답 후 폐기)
- mode=post   : VOC를 지파넷 게시판에 본인 명의로 등록
검증된 방식: m_id/m_pass 로그인 → write.asp 선방문(필드 자동 파싱) → EUC-KR multipart 전송
"""
from http.server import BaseHTTPRequestHandler
import json
import re

import requests

LOGIN_URL      = "http://dev.gngline.com/assets/login/login_action.asp"
WRITE_PAGE_URL = "http://old.gngline.com/images/gng_netw/gn_net025_write.asp"
WRITE_PROC_URL = "http://old.gngline.com/images/gng_netw/gn_net025_write1.asp"

SEV_LABEL = {1: "경미", 2: "주의", 3: "보통", 4: "심각", 5: "긴급"}


def parse_hidden(html, name, default=""):
    """write.asp HTML에서 hidden 필드 값 추출.
    name 뒤에 따옴표/공백/꺾쇠가 와야 매칭 → writer가 writerid에 오매칭되는 것 방지."""
    # name="writer" 처럼 정확히 끝나는 경우만 (뒤에 따옴표 또는 공백/> )
    boundary = r'(?=["\'\s>])'
    m = re.search(
        r'name=["\']?' + re.escape(name) + boundary + r'[^>]*?value=["\']([^"\']*)["\']',
        html, re.IGNORECASE)
    if not m:
        m = re.search(
            r'value=["\']([^"\']*)["\'][^>]*?name=["\']?' + re.escape(name) + boundary,
            html, re.IGNORECASE)
    return m.group(1) if m else default


def gipanet_session(user_id, user_pw):
    """로그인 후 글쓰기 페이지 필드 파싱. 반환: (session, info dict) 또는 (None, 오류문)"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Referer": WRITE_PAGE_URL,
    })
    try:
        s.post(LOGIN_URL, data={
            "memory": "on",
            "_Command": "login",
            "id": user_id,
            "password": user_pw,
        }, timeout=12)
        r = s.get(WRITE_PAGE_URL, timeout=12)
        html = r.content.decode("euc-kr", errors="replace")
    except Exception as e:
        return None, f"지파넷 접속 오류: {e}"

    # 로그인 성공 판정: 서버가 writerid를 채워줬는가 (구형 ASP는 따옴표 없는 name=subject라 subject 검사 불가)
    writerid_check = parse_hidden(html, "writerid", "")
    if not writerid_check:
        return None, "로그인 실패 — 아이디/비밀번호를 확인해주세요"

    info = {
        "writerid":    parse_hidden(html, "writerid", user_id),
        "writer":      parse_hidden(html, "writer", ""),
        "email":       parse_hidden(html, "email", ""),
        "r_board_key": parse_hidden(html, "r_board_key", ""),
        "bbsTerm":     parse_hidden(html, "bbsTerm", "A"),
        "max_1":       parse_hidden(html, "max_1", "0"),
    }
    return s, info


def do_post_voc(user_id, user_pw, voc):
    s, info = gipanet_session(user_id, user_pw)
    if s is None:
        return {"ok": False, "error": info}

    sev = int(voc.get("severity", 3))
    title = f"[GSV][{voc.get('site','')}] {voc.get('title','')} ({SEV_LABEL.get(sev,'보통')})"
    body_text = (
        f"■ 사업장: {voc.get('site','')}<br>"
        f"■ 유형: {voc.get('type','')}<br>"
        f"■ 심각도: {sev} ({SEV_LABEL.get(sev,'보통')})<br><br>"
        f"■ 상황 요약<br>-{voc.get('summary','')}<br><br>"
        f"■ 조치 내용<br>-{voc.get('action','')}<br><br>"
        f"※ GSV(G&G Smart VOC) 자동 등록 / 작성: {info['writer'] or user_id}"
    )
    fields = {
        "content":     f"<p>{body_text}</p>",
        "dummy":       "",
        "writerid":    info["writerid"],
        "writer":      info["writer"],
        "r_board_key": info["r_board_key"],
        "filemvsize":  "",
        "email":       info["email"],
        "subject":     title,
        "max_1":       info["max_1"],
        "bbsTerm":     info["bbsTerm"],
    }
    files = [(k, (None, v.encode("euc-kr", errors="replace"))) for k, v in fields.items()]
    for img in ["image","image1","image2","image3","image4","image5","image6","image7","image8"]:
        files.append((img, ("", b"", "application/octet-stream")))

    try:
        r = s.post(WRITE_PROC_URL, files=files, timeout=20)
        if r.status_code == 200 and "VBScript" not in r.text:
            return {"ok": True, "title": title, "writer": info["writer"] or user_id}
        return {"ok": False, "error": f"등록 실패 (응답 {r.status_code})"}
    except Exception as e:
        return {"ok": False, "error": f"등록 전송 오류: {e}"}
    finally:
        user_pw = None  # 명시적 폐기
        s.close()


class handler(BaseHTTPRequestHandler):
    def _reply(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        self._reply(200, {"ok": True, "service": "GSV register API", "hint": "POST로 사용하세요"})

    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._reply(400, {"ok": False, "error": "잘못된 요청"})

        mode = body.get("mode")
        user_id = (body.get("id") or "").strip()
        user_pw = body.get("pw") or ""
        if not user_id or not user_pw:
            return self._reply(400, {"ok": False, "error": "아이디/비밀번호가 필요합니다"})

        if mode == "verify":
            s, info = gipanet_session(user_id, user_pw)
            if s is None:
                return self._reply(200, {"ok": False, "error": info})
            s.close()
            return self._reply(200, {"ok": True,
                                     "writer": info["writer"] or user_id,
                                     "writerid": info["writerid"]})

        if mode == "post":
            result = do_post_voc(user_id, user_pw, body.get("voc") or {})
            return self._reply(200, result)

        return self._reply(400, {"ok": False, "error": "알 수 없는 mode"})
