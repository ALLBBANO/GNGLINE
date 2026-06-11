# -*- coding: utf-8 -*-
"""
GSV 진단 API — 클라우드에서 지파넷에 접속이 되는지 단계별로 확인
브라우저에서 https://gngline.vercel.app/api/diag 열면 결과가 JSON으로 나옴
(비밀번호 불필요 — 접속 가능 여부만 확인)
"""
from http.server import BaseHTTPRequestHandler
import json
import requests

LOGIN_URL      = "http://dev.gngline.com/login_responsive.asp"
WRITE_PAGE_URL = "http://old.gngline.com/images/gng_netw/gn_net025_write.asp"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = {"steps": []}

        # 1) dev.gngline.com 로그인 페이지에 GET 되나?
        try:
            r = requests.get(LOGIN_URL, timeout=10)
            result["steps"].append({
                "step": "dev.gngline.com 접속",
                "ok": True,
                "status": r.status_code,
                "length": len(r.content),
            })
        except Exception as e:
            result["steps"].append({
                "step": "dev.gngline.com 접속",
                "ok": False,
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            })

        # 2) old.gngline.com 글쓰기 페이지에 GET 되나?
        try:
            r = requests.get(WRITE_PAGE_URL, timeout=10)
            result["steps"].append({
                "step": "old.gngline.com 접속",
                "ok": True,
                "status": r.status_code,
                "length": len(r.content),
            })
        except Exception as e:
            result["steps"].append({
                "step": "old.gngline.com 접속",
                "ok": False,
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            })

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
