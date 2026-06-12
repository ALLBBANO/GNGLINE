# -*- coding: utf-8 -*-
"""
GSV 진단 API v2 — 로그인 시도까지 확인
POST로 {id, pw} 보내면 로그인 단계별 결과를 JSON으로 반환 (비번은 응답에 포함 안 함)
GET으로 열면 접속 가능 여부만 확인
"""
from http.server import BaseHTTPRequestHandler
import json
import re
import requests

LOGIN_URL      = "http://dev.gngline.com/assets/login/login_action.asp"
WRITE_PAGE_URL = "http://old.gngline.com/images/gng_netw/gn_net025_write.asp"


def check_get():
    out = []
    for label, url in [("dev 로그인페이지", LOGIN_URL), ("old 글쓰기페이지", WRITE_PAGE_URL)]:
        try:
            r = requests.get(url, timeout=10)
            out.append({"step": label, "ok": True, "status": r.status_code, "length": len(r.content)})
        except Exception as e:
            out.append({"step": label, "ok": False, "error": f"{type(e).__name__}: {str(e)[:150]}"})
    return out


def check_login(user_id, user_pw):
    out = []
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Referer": WRITE_PAGE_URL,
    })
    # 1) 로그인 POST
    try:
        r = s.post(LOGIN_URL, data={
            "memory": "on",
            "_Command": "login",
            "id": user_id,
            "password": user_pw,
        }, timeout=12)
        body = r.content.decode("euc-kr", errors="replace")
        out.append({
            "step": "로그인 POST (id/password/_Command)",
            "status": r.status_code,
            "length": len(body),
            "cookies": list(s.cookies.get_dict().keys()),
            "has_login_word": ("로그인" in body),
            "has_logout_word": ("로그아웃" in body or "logout" in body.lower()),
            "body_head": body[:200].replace("\n", " ").replace("\r", " "),
        })
    except Exception as e:
        out.append({"step": "로그인 POST", "error": f"{type(e).__name__}: {str(e)[:150]}"})
        return out

    # 2) 글쓰기 페이지 접근해서 로그인 됐는지 확인
    try:
        r = s.get(WRITE_PAGE_URL, timeout=12)
        html = r.content.decode("euc-kr", errors="replace")
        has_subject = ('name="subject"' in html or "name='subject'" in html)
        # writerid hidden 값 추출 시도
        m = re.search(r'name=["\']?writerid["\']?[^>]*?value=["\']([^"\']*)["\']', html, re.IGNORECASE)
        out.append({
            "step": "글쓰기 페이지 접근",
            "status": r.status_code,
            "length": len(html),
            "has_subject_field": has_subject,
            "writerid_found": (m.group(1) if m else None),
            "login_form_present": ("m_pass" in html or 'type="password"' in html),
        })
    except Exception as e:
        out.append({"step": "글쓰기 페이지 접근", "error": f"{type(e).__name__}: {str(e)[:150]}"})
    return out


class handler(BaseHTTPRequestHandler):
    def _reply(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def do_GET(self):
        self._reply(200, {"mode": "GET 접속확인", "steps": check_get()})

    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._reply(400, {"error": "잘못된 요청"})
        uid = (body.get("id") or "").strip()
        pw = body.get("pw") or ""
        if not uid or not pw:
            return self._reply(400, {"error": "id/pw 필요"})
        self._reply(200, {"mode": "POST 로그인진단", "steps": check_login(uid, pw)})
