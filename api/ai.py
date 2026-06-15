# -*- coding: utf-8 -*-
"""
GSV AI API (Vercel 서버리스 함수)
- mode=questions : 한 줄 입력을 보고 추가 질문 생성 (최대 2개)
- mode=structure : 정형화 양식 + 심각도 제안
Anthropic API 키는 Vercel 환경변수 ANTHROPIC_API_KEY 사용 (프론트에 노출 안 됨)
"""
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import urllib.request

MODEL = "claude-sonnet-4-5"
ESCALATION_WORDS = ["본사", "소비자원", "환불", "신고", "부상", "고소", "언론", "블랙컨슈머"]


def call_claude(prompt):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다")
    payload = json.dumps({
        "model": MODEL,
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    text = "\n".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
    text = re.sub(r"```json|```", "", text).strip()
    return json.loads(text)


def make_questions(site, raw):
    prompt = (
        "당신은 유통 현장 컴플레인(VOC) 접수 도우미입니다. 현장 팀장이 아래 한 줄 보고를 입력했습니다.\n\n"
        f"사업장: {site}\n보고 내용: \"{raw}\"\n\n"
        "정확한 접수를 위해 꼭 필요한 추가 질문을 최대 2개만 만드세요. 이미 내용이 충분하면 빈 배열. "
        "질문은 10초 안에 답할 수 있게 짧고 구체적으로, 존댓말로.\n"
        "단, 발생 장소는 절대 묻지 마세요(장소는 별도로 처리됨). 질문은 심각도 판단이나 예측 분석에 중요한 것에만 쓰세요.\n\n"
        '반드시 아래 JSON만 출력 (다른 텍스트/마크다운 금지):\n{"questions": ["질문1", "질문2"]}'
    )
    d = call_claude(prompt)
    return {"ok": True, "questions": (d.get("questions") or [])[:2]}


def make_structure(site, raw, qa):
    qa_text = "\n".join(f"Q{i+1}. {p.get('q','')}\nA{i+1}. {p.get('a') or '(무응답)'}"
                        for i, p in enumerate(qa or [])) or "(추가 질문 없음)"
    prompt = (
        "당신은 유통 현장 컴플레인(VOC) 접수 도우미입니다. 아래 정보를 정형화된 접수 양식으로 변환하세요.\n\n"
        f"사업장: {site}\n팀장 최초 보고: \"{raw}\"\n추가 문답:\n{qa_text}\n\n"
        "규칙:\n- 입력에 없는 사실을 지어내지 말 것. 모르면 \"확인 필요\".\n"
        "- 심각도 1(경미)~5(긴급): 1-2 현장 즉시 해결, 3 조치 필요/재발 우려, 4 본사 확인 필수, 5 본사·원청·외부기관/안전사고.\n"
        "- 환불/본사/소비자원/신고/부상/언론 등 확산 위험 키워드는 최소 4 이상.\n\n"
        "추가로, 나중의 컴플레인 예측 분석을 위해 아래 태그도 입력 내용에서 추출하세요(없으면 \"미상\"):\n"
        "- cause: 유발요인 (인력부족|상품결함|시스템오류|안내미흡|고객과실|시설문제|기타)\n"
        "- customer_demand: 고객요구 (환불|교환|사과|보상|개선요구|단순불만|기타)\n"
        "- repeat_signal: 반복성 신호 (true=이전에도 비슷한 일이 있었다는 언급/정황, false=없음)\n\n"
        "반드시 아래 JSON만 출력 (다른 텍스트/마크다운 금지):\n"
        '{"type": "응대태도|대기시간|상품품질|계산오류|시설환경|기타 중 하나", "title": "15자 내외 제목", '
        '"summary": "발생 상황 2~3문장", "action": "조치 내용 또는 미조치", "severity": 3, "reason": "제안 근거 1문장", '
        '"cause": "유발요인", "customer_demand": "고객요구", "repeat_signal": false}'
    )
    d = call_claude(prompt)
    all_text = raw + " " + " ".join((p.get("a") or "") for p in (qa or []))
    hits = [w for w in ESCALATION_WORDS if w in all_text]
    sev = max(1, min(5, int(d.get("severity", 3))))
    if hits and sev < 4:
        sev = 4
        d["reason"] = f"확산 위험 키워드({', '.join(hits)}) 감지로 상향 제안"
    d["severity"] = sev
    d["escalated"] = hits
    return {"ok": True, "draft": d}


class handler(BaseHTTPRequestHandler):
    def _reply(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        self._reply(200, {"ok": True, "service": "GSV ai API", "hint": "POST로 사용하세요"})

    def do_POST(self):
        try:
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            mode = body.get("mode")
            site = body.get("site", "")
            raw = body.get("raw", "")
            if mode == "questions":
                return self._reply(200, make_questions(site, raw))
            if mode == "structure":
                return self._reply(200, make_structure(site, raw, body.get("qa")))
            return self._reply(400, {"ok": False, "error": "알 수 없는 mode"})
        except Exception as e:
            return self._reply(200, {"ok": False, "error": f"AI 처리 오류: {e}"})
