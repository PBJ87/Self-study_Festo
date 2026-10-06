import csv
import html
import io
import json
import sqlite3
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
DB_FILE = APP_DIR / "customer_visits.db"
HOST, PORT = "127.0.0.1", 8765
STATUSES = ("진행 예정", "진행 중", "진행 완료", "진행 보류", "취소")
LEGACY = {"예정": "진행 예정", "완료": "진행 완료", "보류": "진행 보류"}
PREFIX = "__CVM_PEOPLE_V1__"


def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, customer TEXT NOT NULL,
            visit_date TEXT NOT NULL, location TEXT, attendees TEXT, purpose TEXT,
            discussion TEXT, customer_requests TEXT, follow_up TEXT,
            status TEXT NOT NULL, additional_notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def pack_people(attendees, se, ae):
    return PREFIX + json.dumps({"version": 1, "attendees": attendees, "se": se, "ae": ae}, ensure_ascii=False)


def unpack_people(value):
    value = value or ""
    if not value.startswith(PREFIX):
        return value, "", ""
    try:
        p = json.loads(value[len(PREFIX):])
        return str(p.get("attendees", "")), str(p.get("se", "")), str(p.get("ae", ""))
    except Exception:
        return value, "", ""


def item(row):
    attendees, se, ae = unpack_people(row["attendees"])
    return {"id": row["id"], "customer": row["customer"] or "", "visit_date": row["visit_date"] or "",
            "location": row["location"] or "", "attendees": attendees, "se": se, "ae": ae,
            "purpose": row["purpose"] or "", "discussion": row["discussion"] or "",
            "customer_requests": row["customer_requests"] or "", "follow_up": row["follow_up"] or "",
            "status": LEGACY.get(row["status"], row["status"] or "진행 예정"),
            "additional_notes": row["additional_notes"] or ""}


def validate(p):
    customer = str(p.get("customer", "")).strip()
    date = str(p.get("visit_date", "")).strip()
    if not customer:
        raise ValueError("고객사를 입력해 주세요.")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("방문 날짜를 YYYY-MM-DD 형식으로 입력해 주세요.")
    status = str(p.get("status", "진행 예정")).strip()
    if status not in STATUSES:
        raise ValueError("올바른 진행 상태를 선택해 주세요.")
    t = lambda k: str(p.get(k, "")).strip()
    return (customer, date, t("location"), pack_people(t("attendees"), t("se"), t("ae")),
            t("purpose"), t("discussion"), t("customer_requests"), t("follow_up"), status, t("additional_notes"))


PAGE = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>고객 방문 메모</title>
<style>
:root{--festo:#009fe3;--festo-dark:#007db4;--ink:#2f3438;--muted:#66727c;--line:#c8d1d8;--panel:#f1f4f6;--white:#fff}
*{box-sizing:border-box}body{margin:0;background:#eef1f3;color:var(--ink);font-family:"Malgun Gothic","Segoe UI",Arial,sans-serif;font-size:14px}header{height:92px;padding:0 28px;background:#fff;border-bottom:4px solid var(--festo);display:flex;align-items:center;justify-content:space-between}.brand-title h1{margin:0;font-size:28px;font-weight:500}.brand-title small{display:block;margin-top:6px;color:var(--muted)}.festo-logo{display:flex;align-items:center;justify-content:flex-end}.festo-logo img{display:block;width:118px;height:auto;object-fit:contain}.layout{max-width:1560px;margin:auto;padding:22px;display:grid;grid-template-columns:43% 57%;gap:18px}.card{background:#f7f9fa;border:1px solid var(--line);border-radius:0;padding:18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}h2{font-size:18px;font-weight:500;margin:0 0 16px;padding-bottom:10px;border-bottom:1px solid var(--line)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px 18px}.field{display:flex;flex-direction:column;gap:6px}.full{grid-column:1/-1}label{font-size:13px;font-weight:600}input,select,textarea{font:inherit;width:100%;padding:9px 10px;border:0;border-bottom:1px solid #aebbc4;border-radius:0;background:#fff;color:var(--ink);outline:none}input:focus,select:focus,textarea:focus{border-bottom:2px solid var(--festo);box-shadow:0 2px 0 rgba(0,159,227,.08)}textarea{min-height:82px;resize:vertical}.buttons{display:flex;gap:9px;flex-wrap:wrap;margin-top:15px}button{padding:9px 16px;border:1px solid #aebbc4;border-radius:3px;background:#fff;color:#293238;font-weight:500;cursor:pointer}button:hover{border-color:var(--festo);color:var(--festo-dark)}button:disabled{opacity:.55;cursor:wait}.primary{background:var(--festo);color:#fff;border-color:var(--festo)}.primary:hover{background:var(--festo-dark);color:#fff}.danger{color:#c62828}.list-toolbar{display:flex;gap:8px;align-items:center;margin:0 0 14px}.list-toolbar .hint{margin-left:auto;color:var(--muted);font-size:12px}.search-panel{padding:14px;background:#eef2f4;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.search-actions{justify-content:flex-end}.date-line{display:grid;grid-template-columns:1fr auto;gap:8px}.tablebox{overflow:auto;max-height:540px;margin-top:14px;border:1px solid var(--line);background:#fff}table{width:100%;border-collapse:collapse;min-width:620px}th,td{padding:10px 8px;border-bottom:1px solid #d8dfe4;text-align:left;font-size:13px}th{position:sticky;top:0;background:#e6eaed;color:#263238;font-weight:600;z-index:1}tbody tr{cursor:pointer}.row-planned td{background:#dff2ff;color:#075985}.row-progress td{background:#fff0bd;color:#805b00}.row-complete td{background:#dff5e7;color:#166534}.row-hold td{background:#e5e8eb;color:#4b5563}.row-cancel td{background:#ffe0e0;color:#b42318}tbody tr:hover td{filter:brightness(.97)}tbody tr.sel td{background:#b8dff5!important;color:#003b5c!important;font-weight:600}.msg{min-height:22px;margin-top:9px;font-size:13px;color:var(--muted)}.err{color:#c62828}.ok{color:#167443}.state{margin-right:auto;color:var(--muted);font-size:13px;align-self:center}.calendar-overlay{position:fixed;inset:0;background:rgba(34,44,52,.3);display:none;align-items:center;justify-content:center;z-index:1000}.calendar-overlay.open{display:flex}.calendar{width:360px;background:#f5f7f8;border:1px solid #9ca8b0;padding:14px;box-shadow:0 12px 36px rgba(0,0,0,.22)}.calendar-head{display:grid;grid-template-columns:44px 1fr 44px;align-items:center;gap:8px;margin-bottom:10px}.calendar-title{text-align:center;font-weight:bold;font-size:17px}.weekdays,.calendar-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:5px}.weekday{text-align:center;font-size:12px;padding:4px}.sun{color:#c62828!important}.sat{color:#0768d7!important}.calendar-day{height:36px;padding:0;background:#fff;font-weight:normal}.calendar-day.outside{visibility:hidden}.calendar-day.today{font-weight:bold;border-color:var(--festo)}.calendar-day.selected{background:var(--festo);color:#fff!important}.calendar-foot{display:flex;justify-content:space-between;margin-top:12px}@media(max-width:980px){.layout{grid-template-columns:1fr}header{height:auto;padding:18px 20px}}@media(max-width:620px){.layout{padding:8px}.grid{grid-template-columns:1fr}.full{grid-column:auto}.list-toolbar .hint{display:none}.festo-logo img{width:96px}}
</style></head><body><header><div class="brand-title"><h1>고객 방문 메모</h1><small>방문 기록과 후속 작업을 한 곳에서 관리합니다.</small></div><div class="festo-logo"><img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAJ4AAAAaCAYAAABGpOW1AAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAYfSURBVHhe7Zp7bFNVHMe/faztWNetHd3Yg22MdFtBBTbBCOMhGFHklQDiH7qJiDJAMZhoQiQh0b8UI4vRPxR8LJGgEnnMwTbAtzxMIAPCXmxjc4OOvVrGButoO/+Yw/bcc9r7tC70k/SPfs+999x77vec3++ce1TDw8PDiBDhP0altPGWfl2Hy513SFkSi7LisGdFFnafdqDkTAdZLAtvFqSgeGbSvf+7/riO8gYXWlzugOOEMC5KDbs1GtvnpSIvOQYA4Pb4MPfzGnQN3CUPl4xRp8HxIjsmGKMAAA09g9j5UxvqugbhHPSQh/MmzaTDwklx2D4vBXqtmizmhbizBFDfPUhKkqnrHjFyY694E4SipuvfzlL0fRM+/vOGJNMBwO27Ppy7PoBV+xvwc0sfAOCm26uI6QCgf8gLx60hAEB1xwAWl9bidFu/JNMBQHvfEEovdGHNt1fIIt4obryxTlm9E7+2jphETrafaCMlRXmr6i9SksylG7dRWt1NyrwYk8bTqlWkJDvaf6qobLxJFsmC49YQzjsGoFEp+yxatQqtLjcaeuSPPABQ0egiJV4onuPZSqrh8XGrKJxmhTlaQ8q8yE8xYm5GLF492oIf6p1kMeakx+LhlJEcSixPZ5thSzBgcWkt9aU9mDQOCyeZSJnKoTonWilh+p2FE/HctPHYd7EbnUHCbVm9E81O7vnJsTqsnmIBqx/GGbRYN8OKH6/2Yf2hJrIYAFA03Yp4Q+j3cKa9H2fb+0kZJr0GFzY9RMohCYvxssx6nHxhSoAmBpbxKgvtyE4wkLIoFn1ZQ33pZ19+AIkxI0l7KE639aPkjIOUsWlWEuZlhDbvwdpebKtoJWW8MTsZWx6ZQMocqppu4pUjzaSM1VMteP+JDFKm0uf2omDvZdxyewN0rVqFK1unB2h8UDzU0iKJiiaKwEsZSQEwRwAxeClVGHUa3qYDgEcnGrF/jY3z42M6BGkvDc8HZbVTepyelJiY9BpYx2lJWXRbK2482ngq9mZJ1IwXQlfFQbvX/iEv3B4fKSsG7R6EwDqfIQuC4emQhCXUAsAnSyfBHM3tQcGIUquQ75e7sULtxplJmJ/JbzQhMRs0yBkffe//41/VoqmXm+MtyDRhXZ4VOg3/vhsTpYYtwQCDwLWvsnonXjvaQsqctUYWrFDLN1SPQks7xIbasBlPLLufysSKXDMAYHP5VRxtEDerCsZv66cizaQDAKw72HRvzU0u+BpmlMN1Trx+TLzxKhpdKC67SsphNZ6wrvc/oI9IbpXA5bfAOjs9NqBMDt77/Tr2nOsk5fuKMWc8/7xEJUuWwsX/uhvyEzEr1RhQLge7Tjk4M0QWjFSWNxJPV4QxZzyjTvlbJuv45hkbNuQnIkbGut0eHy503Cbl+4aw5XhiJhdatSpgYViJyUW8QYNcv8kFSXXHAAY93Odh4fb4sK2iFb13uN9Hdz6WhqLpVlLmEJlciIBmPFuCAVWF9gBNDFvKW1DewDXeiSI7JlvkWUCWg73nO/HuL9dIGTvmp+LFvERS5nCk3omtEoxX2ejCxvttckHLTygDoCh8jD5DV8NHgsCRnURqe7HOZ8iCYK0RhkJx49G8oRF5sySslXtWQ4vhg1MOPPvdlYDf2yeF7SzpoYRZIUhtL1Y7uQb5TW5GoR0vtq3DEmqzEwyolCHUsnI8OTYJLMsxY7LFgAVf1FA/8K+0W5ARN7LWFwyPbxj7LvZQ98CNbhIIhdQcj7VJIFqrRtEMK/Q8nF3bdQdVTdydOkadBpc2j5FNAkrneHKw0m7Bh09m4KXDzTjZzG1wOTiwNjvgSwwLqTnetb4hFOy9TMqykJ8SgwNrs0k5JIqH2rHKaGdZljPylURussx6XqaTg1STTrG6ludaSIkXYTGeXGPssCzpcXBW5Jp5zTyFkGSMwqfLs0iZiRzt9dGSTEG7UfiwaooFhTxSBRqKGy9nPHdZw/8jvBSCrbdJxf/aO+an4rPlWZibIe3zWXqcHhvyE3G8UNhyT2Y83TA2AddIjtXh2PO5KJ6ZJKhuGnPSY1GyJBO7FvPby0dD8RwvQgQaio94ESLQiBgvQlj4G6TkX/iAjfplAAAAAElFTkSuQmCC" alt="FESTO"></div></header><main class="layout">
<section class="card"><h2>저장된 방문 메모</h2><div class="list-toolbar"><button onclick="fresh()">새 메모</button><button onclick="load()">목록 새로고침</button><button onclick="exportCsv()">CSV 내보내기</button><span class="hint">항목을 더블클릭하면 수정할 수 있습니다.</span></div><div class="search-panel"><div class="grid">
<div class="field"><label>고객사</label><input id="qc"></div><div class="field"><label>진행 상태</label><select id="qs"><option>전체</option></select></div>
<div class="field"><label>방문 월</label><select id="qm"><option>전체</option></select></div><div class="field"><label>날짜 정렬</label><select id="qo"><option value="desc">내림차순</option><option value="asc">오름차순</option></select></div>
<div class="field"><label>SE</label><input id="qse"></div><div class="field"><label>AE</label><input id="qae"></div><div class="field full"><label>키워드</label><input id="qk"></div></div>
<div class="buttons search-actions"><button class="primary" onclick="load()">검색</button><button onclick="resetSearch()">검색 초기화</button></div></div>
<div class="tablebox"><table><thead><tr><th>No.</th><th>방문 날짜</th><th>고객사</th><th>SE</th><th>AE</th><th>상태</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="buttons"><button onclick="openSelected()">선택 항목 열기</button><button class="danger" onclick="removeMemo()">선택 항목 삭제</button></div><div id="listmsg" class="msg"></div></section>
<section class="card"><h2>방문 메모 작성 / 수정</h2><form id="form"><div class="grid">
<div class="field"><label>고객사 *</label><input id="customer" required></div><div class="field"><label>방문 장소</label><input id="location"></div>
<div class="field full"><label>방문 날짜 *</label><div class="date-line"><input id="date" placeholder="YYYY-MM-DD" required><button type="button" onclick="openCalendar()">달력에서 선택</button></div></div><div class="field"><label>SE</label><input id="se"></div><div class="field"><label>AE</label><input id="ae"></div>
<div class="field full"><label>참석자</label><input id="attendees"></div><div class="field full"><label>진행 상태</label><select id="status"></select></div>
<div class="field full"><label>방문 목적</label><textarea id="purpose"></textarea></div><div class="field full"><label>논의 내용</label><textarea id="discussion" style="min-height:130px"></textarea></div>
<div class="field full"><label>고객 요청사항</label><textarea id="requests"></textarea></div><div class="field full"><label>내가 해야 할 후속 작업</label><textarea id="followup"></textarea></div><div class="field full"><label>추가 메모</label><textarea id="notes" rows="4" style="min-height:100px"></textarea></div></div>
<div class="buttons"><span class="state" id="state">새 메모 작성 중</span><button id="saveBtn" class="primary" type="button" onclick="saveMemo()">저장</button><button type="button" onclick="clearInputs()">입력 내용 지우기</button></div><div id="formmsg" class="msg"></div></form></section></main>
<div id="calendarOverlay" class="calendar-overlay" onclick="calendarBackdrop(event)"><div class="calendar" role="dialog" aria-modal="true" aria-label="방문 날짜 선택"><div class="calendar-head"><button type="button" onclick="moveMonth(-1)">◀</button><div id="calendarTitle" class="calendar-title"></div><button type="button" onclick="moveMonth(1)">▶</button></div><div class="weekdays"><div class="weekday sun">일</div><div class="weekday">월</div><div class="weekday">화</div><div class="weekday">수</div><div class="weekday">목</div><div class="weekday">금</div><div class="weekday sat">토</div></div><div id="calendarGrid" class="calendar-grid"></div><div class="calendar-foot"><button type="button" onclick="chooseToday()">오늘</button><button type="button" onclick="closeCalendar()">취소</button></div></div></div>
<script>
const S=["진행 예정","진행 중","진행 완료","진행 보류","취소"];const STATUS_CLASS={"진행 예정":"row-planned","진행 중":"row-progress","진행 완료":"row-complete","진행 보류":"row-hold","취소":"row-cancel"};let chosen=null,editing=null,cache=[],calendarCursor=new Date(),saving=false;const $=x=>document.getElementById(x);const msg=(id,s,c="")=>{$(id).textContent=s;$(id).className="msg "+c};
async function api(u,o={}){let r=await fetch(u,{headers:{"Content-Type":"application/json"},...o}),d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.error||`HTTP ${r.status}`);return d}
S.forEach(s=>{for(const id of ["qs","status"]){let o=document.createElement("option");o.value=s;o.textContent=s;$(id).appendChild(o)}});
async function months(){let d=await api("/api/months"),old=$("qm").value;$("qm").innerHTML='<option>전체</option>'+d.months.map(x=>`<option>${x}</option>`).join("");$("qm").value=d.months.includes(old)?old:"전체"}
function params(){return new URLSearchParams({customer:$("qc").value,status:$("qs").value,month:$("qm").value,sort:$("qo").value,se:$("qse").value,ae:$("qae").value,keyword:$("qk").value})}
async function load(select=null){try{await months();let d=await api("/api/memos?"+params());cache=d.items;$("rows").innerHTML="";d.items.forEach((m,i)=>{let tr=document.createElement("tr");tr.dataset.id=m.id;tr.classList.add(STATUS_CLASS[m.status]||"row-planned");[i+1,m.visit_date,m.customer,m.se,m.ae,m.status].forEach(v=>{let td=document.createElement("td");td.textContent=v||"";tr.appendChild(td)});tr.onclick=()=>choose(m.id);tr.ondblclick=()=>openMemo(m.id);$("rows").appendChild(tr)});if(select)choose(select);msg("listmsg",`${d.items.length}건을 표시했습니다.`,"ok")}catch(e){msg("listmsg",e.message,"err")}}
function choose(id){chosen=+id;document.querySelectorAll("#rows tr").forEach(r=>r.classList.toggle("sel",+r.dataset.id===chosen))}
async function openMemo(id){id=id||chosen;if(!id)return msg("listmsg","메모를 선택해 주세요.","err");try{let m=await api(`/api/memos/${id}`);editing=chosen=m.id;for(const [a,b] of [["customer","customer"],["location","location"],["date","visit_date"],["se","se"],["ae","ae"],["attendees","attendees"],["status","status"],["purpose","purpose"],["discussion","discussion"],["requests","customer_requests"],["followup","follow_up"],["notes","additional_notes"]])$(a).value=m[b]||"";$("state").textContent=`메모 ID ${m.id} 수정 중`;choose(m.id);msg("formmsg","메모를 불러왔습니다.","ok")}catch(e){msg("formmsg",e.message,"err")}}
function openSelected(){openMemo(chosen)}
function defaultForm(){$("form").reset();$("date").value=new Date().toLocaleDateString("sv-SE");$("status").value="진행 예정";$("notes").value="- End user : \n- Competitor :  \n- Project potential : \n- Opportunity number :  ";$("customer").focus()}
function fresh(){editing=chosen=null;defaultForm();$("state").textContent="새 메모 작성 중";document.querySelectorAll("#rows tr").forEach(r=>r.classList.remove("sel"));msg("formmsg","")}
function clearInputs(){fresh();msg("formmsg","입력 내용을 지웠습니다.","ok")}
function payload(){return {customer:$("customer").value,location:$("location").value,visit_date:$("date").value,se:$("se").value,ae:$("ae").value,attendees:$("attendees").value,status:$("status").value,purpose:$("purpose").value,discussion:$("discussion").value,customer_requests:$("requests").value,follow_up:$("followup").value,additional_notes:$("notes").value}}
async function saveMemo(){if(saving)return;if(!$("form").reportValidity())return;saving=true;$("saveBtn").disabled=true;$("saveBtn").textContent="저장 중...";try{let m=await api(editing?`/api/memos/${editing}`:"/api/memos",{method:editing?"PUT":"POST",body:JSON.stringify(payload())});editing=m.id;$("state").textContent=`메모 ID ${m.id} 수정 중`;msg("formmsg","방문 메모를 저장했습니다.","ok");await load(m.id)}catch(e){msg("formmsg",e.message,"err")}finally{saving=false;$("saveBtn").disabled=false;$("saveBtn").textContent="저장"}}
$("form").onsubmit=e=>{e.preventDefault();saveMemo()};
function exportCsv(){window.location.href="/api/export.csv?"+params()}
function parseDateValue(v){let m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(v||"");if(!m)return null;let d=new Date(+m[1],+m[2]-1,+m[3]);return d.getFullYear()===+m[1]&&d.getMonth()===+m[2]-1&&d.getDate()===+m[3]?d:null}
function fmtDate(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`}
function openCalendar(){calendarCursor=parseDateValue($("date").value)||new Date();calendarCursor=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth(),1);renderCalendar();$("calendarOverlay").classList.add("open")}
function closeCalendar(){$("calendarOverlay").classList.remove("open")}
function calendarBackdrop(e){if(e.target===$("calendarOverlay"))closeCalendar()}
function moveMonth(n){calendarCursor=new Date(calendarCursor.getFullYear(),calendarCursor.getMonth()+n,1);renderCalendar()}
function renderCalendar(){let y=calendarCursor.getFullYear(),m=calendarCursor.getMonth(),first=new Date(y,m,1).getDay(),last=new Date(y,m+1,0).getDate(),selected=parseDateValue($("date").value),today=new Date();$("calendarTitle").textContent=`${y}년 ${m+1}월`;let g=$("calendarGrid");g.innerHTML="";for(let i=0;i<first;i++){let x=document.createElement("span");x.className="calendar-day outside";g.appendChild(x)}for(let day=1;day<=last;day++){let d=new Date(y,m,day),b=document.createElement("button");b.type="button";b.className="calendar-day";if(d.getDay()===0)b.classList.add("sun");if(d.getDay()===6)b.classList.add("sat");if(d.toDateString()===today.toDateString())b.classList.add("today");if(selected&&d.toDateString()===selected.toDateString())b.classList.add("selected");b.textContent=day;b.onclick=()=>{$("date").value=fmtDate(d);closeCalendar()};g.appendChild(b)}}
function chooseToday(){let d=new Date();$("date").value=fmtDate(d);closeCalendar()}
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeCalendar()});
async function removeMemo(){let id=chosen||editing;if(!id)return msg("listmsg","삭제할 메모를 선택해 주세요.","err");let m=cache.find(x=>x.id===id);if(!confirm(`'${m?.customer||"선택한 메모"}'를 삭제하시겠습니까?\n삭제한 데이터는 복구할 수 없습니다.`))return;try{await api(`/api/memos/${id}`,{method:"DELETE"});if(editing===id)fresh();await load();msg("listmsg","방문 메모를 삭제했습니다.","ok")}catch(e){msg("listmsg",e.message,"err")}}
function resetSearch(){["qc","qse","qae","qk"].forEach(x=>$(x).value="");$("qs").value=$("qm").value="전체";$("qo").value="desc";load()}
["qs","qm","qo"].forEach(x=>$(x).onchange=()=>load());["qc","qse","qae","qk"].forEach(x=>$(x).onkeydown=e=>{if(e.key==="Enter")load()});fresh();load();
</script></body></html>''' 



class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)
    def send_csv(self, rows):
        out = io.StringIO(newline="")
        w = csv.writer(out)
        w.writerow(["ID", "방문 날짜", "고객사", "방문 장소", "참석자", "SE", "AE", "방문 목적", "논의 내용", "고객 요청사항", "후속 작업", "진행 상태", "추가 메모"])
        for m in rows:
            w.writerow([m["id"], m["visit_date"], m["customer"], m["location"], m["attendees"], m["se"], m["ae"], m["purpose"], m["discussion"], m["customer_requests"], m["follow_up"], m["status"], m["additional_notes"]])
        body = ("\ufeff" + out.getvalue()).encode("utf-8")
        name = "customer_visit_memos_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
        self.send_response(200); self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length", 0))
        if n > 1000000: raise ValueError("요청 데이터가 너무 큽니다.")
        try: return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception: raise ValueError("올바르지 않은 요청입니다.")

    def memo_id(self, path):
        p = path.strip("/").split("/")
        try: return int(p[2]) if len(p) == 3 and p[:2] == ["api", "memos"] else None
        except ValueError: return None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            body = PAGE.encode("utf-8"); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body); return
        if u.path == "/api/months":
            with db() as c: rows = c.execute("SELECT DISTINCT substr(visit_date,1,7) m FROM visits ORDER BY m DESC").fetchall()
            return self.send_json({"months": [r["m"] for r in rows if r["m"]]})
        if u.path == "/api/export.csv": return self.export_csv(parse_qs(u.query))
        if u.path == "/api/memos": return self.list_memos(parse_qs(u.query))
        mid = self.memo_id(u.path)
        if mid is not None:
            with db() as c: row = c.execute("SELECT * FROM visits WHERE id=?", (mid,)).fetchone()
            return self.send_json(item(row) if row else {"error": "메모를 찾을 수 없습니다."}, 200 if row else 404)
        self.send_json({"error": "경로를 찾을 수 없습니다."}, 404)

    def filtered_memos(self, q):
        v=lambda k,d="":q.get(k,[d])[0].strip(); sql="SELECT * FROM visits WHERE 1=1"; p=[]
        if v("customer"): sql+=" AND customer LIKE ?"; p.append("%"+v("customer")+"%")
        if v("status","전체")!="전체": sql+=" AND status IN (?,?)"; p += [v("status"), {"진행 예정":"예정","진행 완료":"완료","진행 보류":"보류"}.get(v("status"),v("status"))]
        if v("month","전체")!="전체": sql+=" AND substr(visit_date,1,7)=?"; p.append(v("month"))
        if v("keyword"):
            sql += " AND (customer LIKE ? OR location LIKE ? OR attendees LIKE ? OR purpose LIKE ? OR discussion LIKE ? OR customer_requests LIKE ? OR follow_up LIKE ? OR additional_notes LIKE ?)"
            p += ["%"+v("keyword")+"%"]*8
        sql += " ORDER BY visit_date " + ("ASC,id ASC" if v("sort","desc")=="asc" else "DESC,id DESC")
        with db() as c: rows=c.execute(sql,p).fetchall()
        out=[]
        for r in rows:
            m=item(r)
            if v("se") and v("se").casefold() not in m["se"].casefold():continue
            if v("ae") and v("ae").casefold() not in m["ae"].casefold():continue
            out.append(m)
        return out

    def export_csv(self, q):
        self.send_csv(self.filtered_memos(q))

    def list_memos(self, q):
        self.send_json({"items":self.filtered_memos(q)})

    def old_list_memos_unused(self, q):
        v=lambda k,d="":q.get(k,[d])[0].strip(); sql="SELECT * FROM visits WHERE 1=1"; p=[]
        if v("customer"): sql+=" AND customer LIKE ?"; p.append("%"+v("customer")+"%")
        if v("status","전체")!="전체": sql+=" AND status IN (?,?)"; p += [v("status"), {"진행 예정":"예정","진행 완료":"완료","진행 보류":"보류"}.get(v("status"),v("status"))]
        if v("month","전체")!="전체": sql+=" AND substr(visit_date,1,7)=?"; p.append(v("month"))
        if v("keyword"):
            sql += " AND (customer LIKE ? OR location LIKE ? OR attendees LIKE ? OR purpose LIKE ? OR discussion LIKE ? OR customer_requests LIKE ? OR follow_up LIKE ? OR additional_notes LIKE ?)"
            p += ["%"+v("keyword")+"%"]*8
        sql += " ORDER BY visit_date " + ("ASC,id ASC" if v("sort","desc")=="asc" else "DESC,id DESC")
        with db() as c: rows=c.execute(sql,p).fetchall()
        out=[]
        for r in rows:
            m=item(r)
            if v("se") and v("se").casefold() not in m["se"].casefold():continue
            if v("ae") and v("ae").casefold() not in m["ae"].casefold():continue
            out.append(m)
        self.send_json({"items":out})

    def do_POST(self):
        if urlparse(self.path).path != "/api/memos": return self.send_json({"error":"경로를 찾을 수 없습니다."},404)
        try:
            vals=validate(self.read_json())
            with db() as c:
                cur=c.execute("INSERT INTO visits (customer,visit_date,location,attendees,purpose,discussion,customer_requests,follow_up,status,additional_notes) VALUES (?,?,?,?,?,?,?,?,?,?)",vals)
                row=c.execute("SELECT * FROM visits WHERE id=?",(cur.lastrowid,)).fetchone()
            self.send_json(item(row),201)
        except ValueError as e:self.send_json({"error":str(e)},400)
        except sqlite3.Error as e:self.send_json({"error":"데이터베이스 오류: "+str(e)},500)

    def do_PUT(self):
        mid=self.memo_id(urlparse(self.path).path)
        if mid is None:return self.send_json({"error":"경로를 찾을 수 없습니다."},404)
        try:
            vals=validate(self.read_json())
            with db() as c:
                if not c.execute("SELECT 1 FROM visits WHERE id=?",(mid,)).fetchone():return self.send_json({"error":"메모를 찾을 수 없습니다."},404)
                c.execute("UPDATE visits SET customer=?,visit_date=?,location=?,attendees=?,purpose=?,discussion=?,customer_requests=?,follow_up=?,status=?,additional_notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",vals+(mid,))
                row=c.execute("SELECT * FROM visits WHERE id=?",(mid,)).fetchone()
            self.send_json(item(row))
        except ValueError as e:self.send_json({"error":str(e)},400)
        except sqlite3.Error as e:self.send_json({"error":"데이터베이스 오류: "+str(e)},500)

    def do_DELETE(self):
        mid=self.memo_id(urlparse(self.path).path)
        if mid is None:return self.send_json({"error":"경로를 찾을 수 없습니다."},404)
        with db() as c: cur=c.execute("DELETE FROM visits WHERE id=?",(mid,))
        self.send_json({"ok":True} if cur.rowcount else {"error":"메모를 찾을 수 없습니다."},200 if cur.rowcount else 404)


def main():
    init_db(); server=ThreadingHTTPServer((HOST,PORT),Handler)
    print(f"고객 방문 메모 웹 버전: http://{HOST}:{PORT}")
    print("종료: Ctrl+C")
    threading.Timer(0.7,lambda:webbrowser.open(f"http://{HOST}:{PORT}")).start()
    try:server.serve_forever()
    except KeyboardInterrupt:print("\n종료합니다.")
    finally:server.server_close()

if __name__ == "__main__": main()
