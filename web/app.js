"use strict";
/* 농구 연습 계획 화면. 서버가 준 글(계획, 안내, 이야기)은 모델이 만든 것이라 innerHTML을 쓰지 않고 textContent로만 그린다. */
(function () {
  const app = document.getElementById("app");
  const who = document.getElementById("who");
  const whoName = document.getElementById("who-name");
  const logoutBtn = document.getElementById("logout");
  const navEl = document.getElementById("nav");

  // ---- DOM 도우미: 글자는 항상 텍스트 노드로 넣는다 ----------------------------------
  function h(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === false || value == null) continue;
      if (key === "class") node.className = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  // ---- 서버 호출 --------------------------------------------------------------------
  class ApiError extends Error {
    constructor(status, message) {
      super(message);
      this.status = status;
    }
  }

  function errorText(data) {
    const detail = data && data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return "입력 값을 확인해 주세요."; // 스키마 검사 오류는 영어라서 그대로 보여 주지 않는다
    return "요청을 처리하지 못했어요. 잠시 뒤에 다시 시도해 주세요.";
  }

  async function api(path, options) {
    const opts = options || {};
    const response = await fetch(path, {
      method: opts.method || "GET",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
    if (response.status === 204) return null;
    let data = null;
    try {
      data = await response.json();
    } catch (e) {
      data = null;
    }
    if (!response.ok) throw new ApiError(response.status, errorText(data));
    return data;
  }

  function showError(box, message) {
    box.replaceChildren();
    if (message) box.append(h("p", { class: "msg", role: "alert" }, message));
  }

  // ---- 로그인 -----------------------------------------------------------------------
  function renderAuth() {
    who.hidden = true;
    navEl.hidden = true;
    let mode = "login";
    const errorBox = h("div");
    const username = h("input", { type: "text", id: "username", autocomplete: "username", required: true, maxlength: 32 });
    const password = h("input", { type: "password", id: "password", required: true, maxlength: 128 });
    const submit = h("button", { class: "btn", type: "submit" }, "로그인");
    const loginTab = h("button", { class: "btn ghost small", type: "button", "aria-selected": "true" }, "로그인");
    const joinTab = h("button", { class: "btn ghost small", type: "button", "aria-selected": "false" }, "가입");
    const hint = h("p", { class: "hint" }, "");

    function setMode(next) {
      mode = next;
      loginTab.setAttribute("aria-selected", String(next === "login"));
      joinTab.setAttribute("aria-selected", String(next === "join"));
      submit.textContent = next === "login" ? "로그인" : "가입하고 시작하기";
      password.setAttribute("autocomplete", next === "login" ? "current-password" : "new-password");
      hint.textContent = next === "join" ? "아이디는 한글·영문·숫자·_·-로 3~32자, 비밀번호는 8자 이상이에요." : "";
      showError(errorBox, "");
    }
    loginTab.addEventListener("click", () => setMode("login"));
    joinTab.addEventListener("click", () => setMode("join"));

    const form = h(
      "form",
      {
        class: "stack",
        novalidate: true,
        onsubmit: async (event) => {
          event.preventDefault();
          submit.disabled = true;
          showError(errorBox, "");
          try {
            const body = { username: username.value.trim(), password: password.value };
            if (mode === "join") await api("/auth/register", { method: "POST", body });
            await api("/auth/login", { method: "POST", body });
            await renderMain();
          } catch (error) {
            showError(errorBox, error.message);
          } finally {
            submit.disabled = false;
          }
        },
      },
      h("div", { class: "field" }, h("label", { for: "username" }, "아이디"), username),
      h("div", { class: "field" }, h("label", { for: "password" }, "비밀번호"), password),
      hint,
      errorBox,
      submit
    );

    app.replaceChildren(
      h(
        "section",
        { class: "card auth" },
        h("h1", {}, "내 연습 계획 만들기"),
        h("p", { class: "muted" }, "로그인하면 연습 기록이 저장되고, 다음 주 계획의 난이도가 기록에 맞게 바뀌어요."),
        h("div", { class: "tabs", role: "group", "aria-label": "로그인 또는 가입" }, loginTab, joinTab),
        form
      )
    );
    username.focus();
  }

  // ---- 입력 폼 ----------------------------------------------------------------------
  const GOAL_SUGGESTIONS = ["3점슛", "왼손 드리블", "레이업", "패스", "자유투"];
  const EQUIPMENT = ["골대", "콘", "벽"];

  function chip(type, name, value, label, checked) {
    const input = h("input", { type, name, value, checked: checked ? true : false });
    return h("label", { class: "chip" }, input, label || value);
  }

  function buildForm(onSubmit) {
    const beginner = h("input", { type: "checkbox", id: "beginner" });
    const beginnerLabel = h("label", { class: "chip", for: "beginner" }, beginner, "농구를 처음 시작했어요");
    const position = h(
      "select",
      { id: "position" },
      ...[["미정", "아직 정하지 않았어요"], ["가드", "가드"], ["포워드", "포워드"], ["센터", "센터"]].map(([value, label]) =>
        h("option", { value }, label)
      )
    );
    const levelBox = h(
      "div",
      { class: "chips", role: "radiogroup", "aria-label": "실력 수준" },
      chip("radio", "level", "초급", "초급", true),
      chip("radio", "level", "중급", "중급", false),
      chip("radio", "level", "상급", "상급", false)
    );
    const goals = h("input", { type: "text", id: "goals", maxlength: 120, placeholder: "예: 3점슛, 왼손 드리블" });
    const suggest = h(
      "div",
      { class: "suggest" },
      GOAL_SUGGESTIONS.map((g) =>
        h(
          "button",
          {
            type: "button",
            onclick: () => {
              const current = goals.value.split(",").map((s) => s.trim()).filter(Boolean);
              if (!current.includes(g) && current.length < 5) goals.value = current.concat(g).join(", ");
            },
          },
          "+ " + g
        )
      )
    );
    const days = h("input", { type: "number", id: "days", min: 1, max: 7, value: 3, inputmode: "numeric" });
    const minutes = h("input", { type: "number", id: "minutes", min: 5, max: 180, value: 40, inputmode: "numeric" });
    const equipmentBox = h("div", { class: "chips" }, EQUIPMENT.map((e) => chip("checkbox", "equipment", e, e, false)));
    const errorBox = h("div");
    const submit = h("button", { class: "btn", type: "submit" }, "계획 만들기");

    const levelField = h("div", { class: "field" }, h("span", { class: "legend" }, "실력 수준"), levelBox);
    const positionField = h("div", { class: "field" }, h("label", { for: "position" }, "포지션"), position);
    beginner.addEventListener("change", () => {
      levelField.hidden = positionField.hidden = beginner.checked;
    });

    const form = h(
      "form",
      {
        class: "stack",
        novalidate: true,
        onsubmit: async (event) => {
          event.preventDefault();
          const days_per_week = Number(days.value);
          const minutes_per_session = Number(minutes.value);
          if (!Number.isInteger(days_per_week) || days_per_week < 1 || days_per_week > 7) {
            return showError(errorBox, "주 연습일은 1~7 사이의 정수여야 해요.");
          }
          if (!Number.isInteger(minutes_per_session) || minutes_per_session < 1) {
            return showError(errorBox, "회당 연습 시간은 1분 이상의 정수여야 해요.");
          }
          const body = {
            is_beginner: beginner.checked,
            goals: goals.value.split(",").map((s) => s.trim()).filter(Boolean),
            days_per_week,
            minutes_per_session,
            equipment: Array.from(equipmentBox.querySelectorAll("input:checked")).map((i) => i.value),
          };
          if (!beginner.checked) {
            body.position = position.value;
            body.level = levelBox.querySelector("input:checked").value;
          }
          showError(errorBox, "");
          submit.disabled = true;
          try {
            await onSubmit(body);
          } catch (error) {
            showError(errorBox, error.message);
          } finally {
            submit.disabled = false;
          }
        },
      },
      beginnerLabel,
      positionField,
      levelField,
      h("div", { class: "field" }, h("label", { for: "goals" }, "약점·목표 (쉼표로 구분)"), goals, suggest),
      h(
        "div",
        { class: "row" },
        h("div", { class: "field" }, h("label", { for: "days" }, "주 연습일"), days),
        h("div", { class: "field" }, h("label", { for: "minutes" }, "회당 시간(분)"), minutes)
      ),
      h("div", { class: "field" }, h("span", { class: "legend" }, "있는 장소·장비 (공은 기본이에요)"), equipmentBox),
      errorBox,
      submit
    );

    function fill(input) {
      if (!input) return;
      beginner.checked = !!input.is_beginner && !beginnerLabel.hidden; // 첫 계획이 아니면 입문 선택은 없고, 수준은 마지막 계획 값으로 채운다
      levelField.hidden = positionField.hidden = beginner.checked;
      if (input.position) position.value = input.position;
      const levelInput = levelBox.querySelector(`input[value="${input.level}"]`);
      if (levelInput) levelInput.checked = true;
      goals.value = (input.goals || []).join(", ");
      days.value = input.days_per_week;
      minutes.value = input.minutes_per_session;
      equipmentBox.querySelectorAll("input").forEach((i) => (i.checked = (input.equipment || []).includes(i.value)));
    }
    // "농구를 처음 시작했어요"는 주별 계획을 한 번도 만들지 않은 사용자의 첫 계획에서만 보인다.
    function setFirstPlan(isFirst) {
      beginnerLabel.hidden = !isFirst;
      if (!isFirst && beginner.checked) {
        beginner.checked = false;
        levelField.hidden = positionField.hidden = false;
      }
    }
    return { node: h("section", { class: "card form-card" }, h("h2", {}, "내 조건"), form), fill, setFirstPlan, submit: () => form.requestSubmit() };
  }

  // ---- 확인 팝업 (<dialog>) ----------------------------------------------------------------
  // 되돌릴 수 없는 일을 하기 전에 사용자의 확인을 받는다. 취소(버튼, Esc)가 기본이고, 확인 버튼을 눌러야만 true.
  function confirmDialog({ title, lines, okText }) {
    return new Promise((resolve) => {
      const dialog = h("dialog", { class: "confirm-dialog", "aria-labelledby": "confirm-title" });
      const cancel = h("button", { class: "btn ghost", type: "button", onclick: () => dialog.close("cancel") }, "취소");
      const ok = h("button", { class: "btn danger", type: "button", onclick: () => dialog.close("ok") }, okText);
      dialog.append(h("h3", { id: "confirm-title" }, title), ...lines.map((line) => h("p", {}, line)), h("div", { class: "row" }, cancel, ok));
      dialog.addEventListener("close", () => {
        const yes = dialog.returnValue === "ok";
        dialog.remove();
        resolve(yes);
      });
      document.body.append(dialog);
      dialog.showModal();
      cancel.focus(); // 실수로 Enter를 눌러도 삭제되지 않게 취소에 초점을 둔다
    });
  }

  // "생성 중" 화면: 농구공이 통통 튀는 애니메이션(SVG+CSS, 외부 이미지 없음)과 경과 시간. 계획이 만들어지면 보드 내용이 통째로 바뀌므로 저절로 사라진다.
  // 움직임을 줄이는 설정이면 CSS가 애니메이션을 끄고 가만히 있는 공만 보여 준다.
  function generatingPanel() {
    const ball = s(
      "svg",
      { class: "ball", viewBox: "0 0 64 64", "aria-hidden": "true", focusable: "false" },
      s("g", { class: "ball-spin" },
        s("circle", { class: "ball-fill", cx: 32, cy: 32, r: 30 }),
        s("path", { class: "ball-seam", d: "M32 2 V62 M2 32 H62 M10 10 C22 22 22 42 10 54 M54 10 C42 22 42 42 54 54" })
      )
    );
    const secs = h("span", { class: "secs" }, "0초");
    const panel = h(
      "div",
      { class: "loading generating", role: "status", "aria-live": "polite" },
      h("div", { class: "court", "aria-hidden": "true" }, ball, h("span", { class: "ball-shadow" })),
      h("p", { class: "gen-title" }, "계획을 만드는 중이에요"),
      h("p", { class: "muted" }, "20초쯤 걸려요 · 경과 ", secs),
      h("p", { class: "hint" }, "그동안 오늘의 농구 이야기를 읽어 보세요.")
    );
    const started = Date.now();
    const timer = setInterval(() => {
      if (!panel.isConnected) return clearInterval(timer); // 계획이 나와서 이 화면이 사라지면 멈춘다
      secs.textContent = `${Math.floor((Date.now() - started) / 1000)}초`;
    }, 1000);
    return panel;
  }

  const hooks = { deletePlan: null }; // 본 화면이 채우는 동작 (보드가 삭제 버튼을 그릴 때 쓴다)

  // ---- 주 계산 (ISO 8601 주, 월요일에 시작. 서버의 week_key와 같은 규칙) ---------------------------
  const DAY_MS = 86400000;
  const WEEK_RANGE = 52; // 서버가 받는 범위: 이번 주 기준 앞뒤 52주

  function weekMonday(key) {
    const m = /^(\d{4})-W(\d{2})$/.exec(key || "");
    if (!m) return null;
    const jan4 = new Date(Date.UTC(Number(m[1]), 0, 4));
    const week1Monday = jan4.getTime() - ((jan4.getUTCDay() + 6) % 7) * DAY_MS;
    return new Date(week1Monday + (Number(m[2]) - 1) * 7 * DAY_MS);
  }

  function weekKeyOf(date) {
    const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7) + 3); // 그 주의 목요일이 속한 해가 주의 해다
    const jan4 = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
    const week1Thursday = jan4.getTime() - ((jan4.getUTCDay() + 6) % 7) * DAY_MS + 3 * DAY_MS;
    const week = 1 + Math.round((d.getTime() - week1Thursday) / (7 * DAY_MS));
    return `${d.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
  }

  function shiftWeek(key, n) {
    return weekKeyOf(new Date(weekMonday(key).getTime() + n * 7 * DAY_MS));
  }

  function weeksBetween(key, base) {
    return Math.round((weekMonday(key).getTime() - weekMonday(base).getTime()) / (7 * DAY_MS));
  }

  function weekLabel(key) {
    const monday = weekMonday(key);
    if (!monday) return key;
    const sunday = new Date(monday.getTime() + 6 * DAY_MS);
    return `${monday.getUTCMonth() + 1}/${monday.getUTCDate()} ~ ${sunday.getUTCMonth() + 1}/${sunday.getUTCDate()}`;
  }

  // ---- 연습 기록 (T27) ---------------------------------------------------------------
  const VERDICT_CLASS = { 상향: "up", 유지: "keep", 하향: "down" };
  const RATINGS = ["쉬웠음", "적당", "어려웠음"];

  function verdictBadge(verdict, label) {
    return h("span", { class: "badge " + VERDICT_CLASS[verdict] }, label || verdict);
  }

  // 연습 한 줄(C안): 왼쪽에 이름·난이도·저장 상태 / 세트×반복·시간 / 목적·자세 팁(접힘), 오른쪽에 기록 입력과 저장 버튼.
  // 연습 카드(요일별 한 줄)마다 기록은 한 건이고 다시 저장하면 그 한 건을 갱신한다. 같은 메뉴가 여러 요일에 있어도 카드별로 따로 저장한다.
  // drill.slot = 요일(같은 요일에 같은 메뉴가 또 나오면 "월#2"), sharedCards = 이 주 계획에서 이 메뉴의 카드 수.
  // onSaved가 없으면(초안·아직 오지 않은 주) 기록칸 없이 계획 내용만 보여 준다.
  function itemRow(drill, registry, onSaved, week, sharedCards, dayEntries) {
    const slot = drill.slot;
    const recordable = !!onSaved;
    const state = h("span", { class: "savestate" }); // 기록 없음 / 입력 중(저장 안 됨) / 저장됨 · 값
    const savedMark = h("span", { class: "sr-only", hidden: true }, " (기록 저장됨)"); // 색만으로 구분하지 않도록 스크린리더용 글자
    const flash = h("p", { class: "flash", role: "status" }); // 저장 직후 잠깐 나오는 확인 문구
    const status = h("p", { class: "done" });
    const result = h("div", { class: "result", "aria-live": "polite" });
    const errorBox = h("div", { class: "item-error" });
    const submit = h("button", { class: "save", type: "submit" }, "기록 저장");
    let fields = null;
    let readBody = null;
    let inputKey = () => "";
    let fillSaved = () => {};
    let saved = null; // 저장된 한 건: 슛 {attempts, makes} / 슛 외 {rating} / 없으면 null
    let savedExists = false; // 저장된 기록이 하나라도 있는가 (예전 방식으로 여러 건이면 합계·최빈 값을 saved에 담는다)
    let legacy = 0; // 예전 방식으로 저장된 여러 건의 개수
    let dirty = false;
    let flashTimer = null;

    const savedKey = () => (saved ? (drill.is_shooting ? `${saved.attempts}/${saved.makes}` : saved.rating) : drill.is_shooting ? "/" : "");
    const savedText = () => {
      if (!savedExists) return "";
      if (!saved) return `평가 ${legacy}건`;
      return drill.is_shooting ? `${saved.attempts}회 중 ${saved.makes}회` : saved.rating;
    };
    const drawState = () => {
      state.className = "savestate " + (dirty ? "dirty" : savedExists ? "saved" : "none");
      state.textContent = dirty ? "✎ 입력 중 · 아직 저장 안 됨" : savedExists ? `✓ ${savedText()}` : "기록 전";
      submit.textContent = savedExists ? "수정" : "저장";
    };
    const showFlash = (text) => {
      if (flashTimer) clearTimeout(flashTimer);
      flash.textContent = text;
      flashTimer = setTimeout(() => { flash.textContent = ""; }, 6000);
    };

    if (recordable && drill.is_shooting) {
      const attempts = h("input", { type: "number", min: 1, inputmode: "numeric", placeholder: "시도", "aria-label": `${drill.name} 시도 횟수` });
      const makes = h("input", { type: "number", min: 0, inputmode: "numeric", placeholder: "성공", "aria-label": `${drill.name} 성공 횟수` });
      fields = h("div", { class: "numbers" }, attempts, makes);
      inputKey = () => `${attempts.value}/${makes.value}`;
      fillSaved = () => {
        attempts.value = saved ? String(saved.attempts) : "";
        makes.value = saved ? String(saved.makes) : "";
      };
      readBody = () => {
        const a = Number(attempts.value);
        const m = Number(makes.value);
        if (attempts.value === "" || makes.value === "") return { error: "시도와 성공 횟수를 입력해 주세요." };
        if (!Number.isInteger(a) || a < 1) return { error: "시도 수는 1 이상의 정수여야 해요." };
        if (!Number.isInteger(m) || m < 0) return { error: "성공 수는 0 이상의 정수여야 해요." };
        if (m > a) return { error: `성공 수(${m})가 시도 수(${a})보다 많을 수 없어요.` };
        return { body: { drill: drill.name, shots: [{ attempts: a, makes: m }] }, summary: `${a}회 중 ${m}회` };
      };
    } else if (recordable) {
      const group = drill.name + "-" + slot + "-" + Math.random().toString(36).slice(2, 7);
      fields = h("div", { class: "seg", role: "radiogroup", "aria-label": `${drill.name} 체감 난이도` }, RATINGS.map((r) => chip("radio", group, r, r, false)));
      inputKey = () => (fields.querySelector("input:checked") || { value: "" }).value;
      fillSaved = () => fields.querySelectorAll("input").forEach((i) => (i.checked = !!saved && i.value === saved.rating));
      readBody = () => {
        const checked = fields.querySelector("input:checked");
        if (!checked) return { error: "쉬웠음, 적당, 어려웠음 중 하나를 골라 주세요." };
        return { body: { drill: drill.name, ratings: [checked.value] }, summary: checked.value };
      };
    }

    const title = h(
      "h3",
      {},
      drill.name,
      savedMark,
      h("span", { class: "lv" }, drill.difficulty),
      drill.is_shooting ? h("span", { class: "lv" }, "슛") : null,
      recordable ? state : null
    );
    const tips = h(
      "details",
      { class: "tip" },
      h("summary", {}, "목적과 자세 팁"),
      h("p", {}, drill.purpose),
      drill.tip ? h("p", {}, "자세 팁: " + drill.tip) : null,
      drill.mistake ? h("p", {}, "흔한 실수: " + drill.mistake) : null
    );
    const main = h("div", { class: "item-main" }, title, h("p", { class: "dose" }, `${drill.sets}세트 × ${drill.reps}회 · ${drill.minutes}분`), tips, recordable ? h("div", { class: "rec-info" }, flash, status, result) : null);
    const row = h(recordable ? "form" : "div", { class: "item", novalidate: recordable ? true : false }, main, recordable ? h("div", { class: "item-input" }, fields, submit) : null, recordable ? errorBox : null);

    if (!recordable) return row;

    row.addEventListener("submit", async (event) => {
      event.preventDefault();
      const parsed = readBody();
      if (parsed.error) {
        showFlash("");
        return showError(errorBox, parsed.error + " (저장되지 않았어요)");
      }
      showError(errorBox, "");
      submit.disabled = true;
      submit.textContent = "저장 중…";
      try {
        await api("/records", { method: "POST", body: { ...parsed.body, week, slot } });
        showFlash(`✓ ${savedExists ? "수정했어요" : "저장했어요"} (${parsed.summary})`);
        await onSaved(); // 같은 메뉴가 여러 날 있는 카드까지 저장된 값을 다시 그린다
      } catch (error) {
        showFlash("");
        showError(errorBox, error.message + " (저장되지 않았어요)");
      } finally {
        submit.disabled = false;
        drawState();
      }
    });
    const refreshDirty = () => {
      dirty = inputKey() !== savedKey();
      drawState();
    };
    row.addEventListener("input", refreshDirty);
    row.addEventListener("change", refreshDirty);
    drawState();

    function update(info) {
      const wasDirty = dirty; // 입력 중이던 값은 덮어쓰지 않는다
      status.replaceChildren();
      result.replaceChildren();
      saved = null;
      savedExists = false;
      legacy = 0;
      if (info && drill.is_shooting && info.shots.length) {
        savedExists = true;
        legacy = info.shots.length;
        saved = { attempts: info.shots.reduce((s, x) => s + x.attempts, 0), makes: info.shots.reduce((s, x) => s + x.makes, 0) };
      } else if (info && !drill.is_shooting && info.ratings.length) {
        savedExists = true;
        legacy = info.ratings.length;
        const counts = RATINGS.map((r) => [r, info.ratings.filter((x) => x === r).length]);
        const top = Math.max(...counts.map(([, n]) => n));
        const winners = counts.filter(([, n]) => n === top);
        saved = winners.length === 1 ? { rating: winners[0][0] } : null; // 동수면 하나로 정할 수 없다
      }
      if (!wasDirty) fillSaved();
      row.classList.toggle("saved", savedExists); // 저장된 줄은 색이 바뀐다
      savedMark.hidden = !savedExists;
      refreshDirty();
      if (!info) return;
      if (legacy > 1) {
        status.append(`예전 방식으로 ${legacy}건이 저장돼 있어서 ${drill.is_shooting ? "합계" : "가장 많은 평가"}로 보여요. 저장하면 한 건으로 바뀌어요.`);
      }
      if (info.carry_over) {
        result.append(verdictBadge("유지", "다음 주 난이도 유지"), h("span", { class: "muted" }, "기록이 없으면 다음 주 계획에 같은 연습을 다시 넣어요."));
      } else {
        result.append(
          verdictBadge(info.verdict, "다음 주 난이도 " + info.verdict),
          h("span", { class: "muted" }, (sharedCards > 1 ? "이 주 모든 카드의 기록을 합쳐서: " : "") + info.reason)
        );
      }
    }
    const entry = { key: `${slot}|${drill.name}`, isSaved: () => savedExists, update };
    registry.push(entry);
    if (dayEntries) dayEntries.push(entry);
    return row;
  }

  // ---- 주간 보드 ---------------------------------------------------------------------
  // 보드를 그리고, 기록 정보를 다시 반영하는 update(rows)를 돌려준다. 위에 월~일 요일 띠, 아래에 고른 요일의 연습 목록(한 번에 한 요일)이 있다.
  // mode: "draft"(승인 대기 초안) | "future"(아직 오지 않은 주) | ""(기록을 입력할 수 있는 주). 앞의 둘은 기록칸이 없다.
  const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];

  function renderBoard(container, plan, mode) {
    const preview = !!mode;
    container.replaceChildren();
    const registry = [];
    const dayRefs = []; // 요일마다 {이름, 띠 버튼, 진행 원, 표시, 목록, 연습들}
    const cardCount = {}; // 메뉴마다 이 주 계획의 카드 수
    (plan ? plan.days : []).forEach((day) => day.drills.forEach((d) => (cardCount[d.name] = (cardCount[d.name] || 0) + 1)));
    let lastRows = [];

    const selectDay = (name) => {
      dayRefs.forEach((d) => {
        const on = d.name === name;
        d.btn.classList.toggle("sel", on);
        d.btn.setAttribute("aria-pressed", String(on));
        d.panel.hidden = !on;
      });
    };
    // 요일 띠의 진행 원·✓와 오른쪽 열의 "이번 주 한눈에" 숫자를 서버가 준 기록으로 다시 계산한다
    const refreshDays = () => {
      dayRefs.forEach((d) => {
        const total = d.entries.length;
        const done = d.entries.filter((e) => e.isSaved()).length;
        const complete = total > 0 && done === total;
        d.btn.classList.toggle("done", complete);
        d.panel.classList.toggle("complete", complete);
        d.mark.hidden = !complete;
        d.pie.style.setProperty("--p", String(total ? Math.round((done / total) * 100) : 0));
        d.small.textContent = preview ? `${d.count}개` : `${done}/${total}`;
      });
      if (preview || !hooks.stats) return;
      const verdicts = { 상향: 0, 유지: 0, 하향: 0 };
      const seen = new Set();
      lastRows.forEach((r) => {
        if (seen.has(r.drill) || r.carry_over) return;
        seen.add(r.drill);
        verdicts[r.verdict] += 1;
      });
      hooks.stats({
        saved: registry.filter((e) => e.isSaved()).length,
        total: registry.length,
        daysDone: dayRefs.filter((d) => d.entries.length > 0 && d.entries.every((e) => e.isSaved())).length,
        daysTotal: dayRefs.length,
        verdicts,
      });
    };
    const update = (rows) => {
      lastRows = rows || [];
      const byCard = new Map(lastRows.map((row) => [`${row.slot}|${row.drill}`, row]));
      registry.forEach((entry) => entry.update(byCard.get(entry.key)));
      refreshDays();
    };
    if (hooks.planShown) hooks.planShown(plan, mode);
    if (!plan) {
      container.append(
        h(
          "div",
          { class: "empty" },
          h("p", {}, "이 주에는 아직 계획이 없어요."),
          hooks.openForm ? h("button", { class: "save big", type: "button", onclick: () => hooks.openForm() }, "조건을 입력하고 계획 만들기") : null
        )
      );
      if (hooks.stats) hooks.stats(null);
      return { update };
    }
    const refresh = preview ? null : async () => update(await api("/records/week?week=" + encodeURIComponent(plan.week)));

    (plan.notices || []).forEach((text) => container.append(h("p", { class: "notice" }, text)));
    if (mode === "future") {
      container.append(h("p", { class: "hint" }, "아직 오지 않은 주예요. 계획만 등록할 수 있고, 기록은 연습한 뒤에 입력해 주세요."));
    } else if (!preview) {
      container.append(
        h("p", { class: "hint" }, "연습한 뒤 각 연습 오른쪽에 기록하면, 이 주의 합계로 다음 주 난이도가 정해져요. 같은 연습이 여러 날 있으면 합계로 계산해요.")
      );
    }

    const strip = h("div", { class: "strip", role: "group", "aria-label": "요일 선택" });
    const panels = h("div", { class: "panels" });
    WEEKDAYS.forEach((name) => {
      const day = plan.days.find((d) => d.day === name);
      if (!day) {
        strip.append(h("span", { class: "day off" }, h("b", {}, name), h("span", { class: "pie" }), h("small", {}, "쉬는 날")));
        return;
      }
      const entries = [];
      const pie = h("span", { class: "pie" });
      const small = h("small", {}, "");
      const btn = h("button", { class: "day", type: "button", "aria-pressed": "false", onclick: () => selectDay(name) }, h("b", {}, name), pie, small);
      const mark = h("span", { class: "okmark", hidden: true }, "✓ 기록 완료");
      const panel = h(
        "section",
        { class: "panel", hidden: true, "aria-label": `${name}요일 연습` },
        h("div", { class: "panelhead" }, h("h2", {}, name + "요일"), h("span", { class: "muted" }, `${day.drills.length}개 연습 · ${day.total_minutes}분`), mark),
        day.drills.map((drill) => itemRow(drill, registry, refresh, plan.week, cardCount[drill.name], entries))
      );
      dayRefs.push({ name, btn, pie, small, panel, mark, entries, count: day.drills.length });
      strip.append(btn);
      panels.append(panel);
    });
    container.append(strip, panels);
    const today = ["일", "월", "화", "수", "목", "금", "토"][new Date().getDay()];
    const names = dayRefs.map((d) => d.name);
    selectDay(hooks.currentWeek && plan.week === hooks.currentWeek() && names.includes(today) ? today : names[0]);
    refreshDays();
    return { update };
  }

  // 승인 대기 중인 초안: 확정하기 전에는 저장되지 않는다. 확정하면 저장되고, 다시 만들기는 같은 조건으로 새 초안을 만든다.
  function showDraft(container, result, formBody, afterDecision) {
    const message = h("div");
    const confirmBtn = h("button", { class: "btn", type: "button" }, "이 계획으로 확정");
    const redoBtn = h("button", { class: "btn ghost", type: "button" }, "다시 만들기");
    const buttons = [confirmBtn, redoBtn];
    const decide = async (decision) => {
      buttons.forEach((b) => (b.disabled = true));
      showError(message, "");
      try {
        return await api(`/plans/${encodeURIComponent(result.plan_id)}/decision`, { method: "POST", body: { decision } });
      } catch (error) {
        showError(message, error.message);
        if (error.status === 404 || error.status === 410) return { status: "gone" }; // 없어졌거나 만료된 초안
        buttons.forEach((b) => (b.disabled = false));
        return null;
      }
    };
    const resets = result.resets_records || 0; // 이미 계획이 있는 주를 다시 만드는 경우, 확정하면 지워질 기록 건수
    const confirm = async () => {
      const done = await decide("confirm");
      if (done && done.status === "confirmed") await afterDecision("confirmed", done.plan);
      else if (done) await afterDecision("gone", null);
    };
    const choices = h("div", { class: "row" }, confirmBtn, redoBtn);
    const askBox = h("div", { class: "warn", role: "alert", hidden: true });
    if (resets > 0) {
      confirmBtn.textContent = `이 계획으로 확정 (기록 ${resets}건 삭제)`;
      confirmBtn.addEventListener("click", () => {
        // 되돌릴 수 없는 삭제라서 한 번 더 확인한다
        const reallyBtn = h("button", { class: "btn danger", type: "button", onclick: confirm }, "기록을 지우고 확정");
        const cancelBtn = h(
          "button",
          { class: "btn ghost", type: "button", onclick: () => { askBox.hidden = true; choices.hidden = false; } },
          "취소"
        );
        buttons.splice(0, buttons.length, reallyBtn, cancelBtn, redoBtn);
        askBox.replaceChildren(
          h("p", {}, `이 주에 입력한 기록 ${resets}건이 지워져요. 되돌릴 수 없고, 다음 주 난이도 판정에도 더는 쓰이지 않아요.`),
          h("div", { class: "row" }, reallyBtn, cancelBtn)
        );
        askBox.hidden = false;
        choices.hidden = true;
      });
    } else {
      confirmBtn.addEventListener("click", confirm);
    }
    redoBtn.addEventListener("click", async () => {
      const done = await decide("reject");
      if (done) await afterDecision("redo", null);
    });
    renderBoard(container, result.plan, "draft");
    container.prepend(
      h(
        "section",
        { class: "banner draft" },
        h("h3", {}, "아직 저장되지 않은 초안이에요"),
        h("p", { class: "muted" }, "마음에 들면 확정해 주세요. 확정해야 이 주 계획으로 저장되고 기록을 입력할 수 있어요. 24시간 안에 확정하지 않으면 사라져요."),
        resets > 0 ? h("p", { class: "msg" }, `이 주에는 이미 계획이 있고 입력한 기록이 ${resets}건 있어요. 이 초안을 확정하면 그 기록이 지워져요.`) : null,
        choices,
        askBox,
        message
      )
    );
  }

  async function showPlan(container, plan, mode) {
    const board = renderBoard(container, plan, mode || "");
    if (plan && !mode) board.update(await api("/records/week?week=" + encodeURIComponent(plan.week)).catch(() => []));
  }

  // ---- 분야별 현황 (T36). 그래프는 외부 라이브러리 없이 SVG로 그리고, 글자는 textContent로만 넣는다 ---------------
  const SVG_NS = "http://www.w3.org/2000/svg";

  function s(tag, attrs, ...kids) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === false || value == null) continue;
      node.setAttribute(key, String(value));
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  // 주별 값을 선 그래프로. 값이 없는 주는 선을 끊고, 표본이 적은 주(hollow)는 속이 빈 점으로 그린다.
  function lineChart({ rows, value, hollow, min, max, ticks, refs, label }) {
    const W = 560, H = 230, L = 66, R = 28, T = 14, B = 36;
    const plotW = W - L - R, plotH = H - T - B;
    const x = (i) => L + (rows.length === 1 ? plotW / 2 : (i * plotW) / (rows.length - 1));
    const y = (v) => T + plotH - ((v - min) / (max - min)) * plotH;
    const parts = [];
    ticks.forEach(([v, text]) => {
      parts.push(s("line", { class: "grid", x1: L, x2: W - R, y1: y(v), y2: y(v) }), s("text", { class: "tick", x: L - 8, y: y(v) + 6, "text-anchor": "end" }, text));
    });
    (refs || []).forEach(([v, text]) => {
      parts.push(s("line", { class: "ref", x1: L, x2: W - R, y1: y(v), y2: y(v) }), s("text", { class: "reftext", x: W - R - 2, y: y(v) - 3, "text-anchor": "end" }, text));
    });
    rows.forEach((row, i) => parts.push(s("text", { class: "tick", x: x(i), y: H - 10, "text-anchor": "middle" }, row.week.slice(5))));
    let path = "";
    let connected = false; // 바로 앞 주에 값이 있었으면 이어서 그리고, 없었으면(기록 없는 주) 선을 끊고 새로 시작한다
    rows.forEach((row, i) => {
      const v = value(row);
      if (v == null) { connected = false; return; }
      path += `${connected ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
      connected = true;
    });
    parts.push(s("path", { class: "line", d: path.trim() }));
    rows.forEach((row, i) => {
      const v = value(row);
      if (v == null) return;
      parts.push(s("circle", { class: "dot" + (hollow(row) ? " hollow" : ""), cx: x(i), cy: y(v), r: 4.5 }));
    });
    return s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label, preserveAspectRatio: "xMidYMid meet" }, s("title", {}, label), parts);
  }

  const ARROW = { up: "▲", down: "▼", flat: "■", insufficient: "…", none: "" };
  const TREND_CLASS = { up: "up", down: "down", flat: "keep", insufficient: "", none: "" };

  function trendLine(kind, trend) {
    if (!trend || trend.status === "none") return null;
    return h("p", { class: "trend" }, h("span", { class: "badge " + (TREND_CLASS[trend.status] || "") }, `${ARROW[trend.status]} ${kind}`), " ", trend.text);
  }

  function verdictCell(v) {
    const parts = [];
    if (v["상향"]) parts.push(h("span", { class: "badge up" }, `상향 ${v["상향"]}`));
    if (v["유지"]) parts.push(h("span", { class: "badge keep" }, `유지 ${v["유지"]}`));
    if (v["하향"]) parts.push(h("span", { class: "badge down" }, `하향 ${v["하향"]}`));
    return h("td", { class: "verdicts" }, parts.length ? parts : "-");
  }

  function fieldCard(f) {
    const rows = f.weeks;
    const hasShots = rows.some((r) => r.attempts > 0);
    const hasRatings = rows.some((r) => r.rating_count > 0);
    const kids = [h("h3", {}, f.field)];
    if (!f.has_data) {
      kids.push(h("p", { class: "muted" }, "아직 기록이 없어요."));
      return h("article", { class: "field-card empty-field" }, kids);
    }
    kids.push(trendLine("성공률", f.shot_trend), trendLine("체감 난이도", f.rating_trend));
    if (hasShots) {
      const last = [...rows].reverse().find((r) => r.rate != null);
      kids.push(
        h("p", { class: "chart-title" }, "주별 슛 성공률 (%)", h("span", { class: "muted" }, " · 속이 빈 점은 시도 20회 미만이라 참고만 해요")),
        lineChart({
          rows, value: (r) => r.rate, hollow: (r) => !r.enough, min: 0, max: 100,
          ticks: [[0, "0"], [20, "20"], [40, "40"], [60, "60"], [80, "80"], [100, "100"]], refs: [[40, "하향 경계 40"], [60, "상향 경계 60"]],
          label: `${f.field} 주별 슛 성공률. 가장 최근 값 ${last ? last.rate + "%" : "없음"}`,
        })
      );
    }
    if (hasRatings) {
      const last = [...rows].reverse().find((r) => r.rating_avg != null);
      kids.push(
        h("p", { class: "chart-title" }, "주별 체감 난이도 평균", h("span", { class: "muted" }, " · 높을수록 쉬워진 거예요")),
        lineChart({
          rows, value: (r) => r.rating_avg, hollow: (r) => r.rating_count < 3, min: 1, max: 3,
          ticks: [[1, "어려움"], [2, "적당"], [3, "쉬움"]], refs: [],
          label: `${f.field} 주별 체감 난이도 평균. 가장 최근 값 ${last ? last.rating_avg + "점" : "없음"}`,
        })
      );
    }
    const head = ["주", ...(hasShots ? ["시도", "성공", "성공률"] : []), ...(hasRatings ? ["평가 수", "평균"] : []), "다음 주 난이도"];
    const body = rows.map((r) =>
      h(
        "tr",
        {},
        h("th", { scope: "row" }, r.week.slice(5)),
        ...(hasShots ? [h("td", {}, r.attempts || "-"), h("td", {}, r.attempts ? r.makes : "-"), h("td", {}, r.rate != null ? r.rate + "%" : "-")] : []),
        ...(hasRatings ? [h("td", {}, r.rating_count || "-"), h("td", {}, r.rating_avg != null ? r.rating_avg : "-")] : []),
        verdictCell(r.verdicts)
      )
    );
    kids.push(
      h(
        "details",
        { class: "datatable" },
        h("summary", {}, "주별 표 보기"),
        h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, head.map((t) => h("th", { scope: "col" }, t)))), h("tbody", {}, body)))
      )
    );
    return h("article", { class: "field-card" }, kids);
  }

  // 종합표: 다섯 분야를 기록이 있는 가장 최근 주 기준으로 한눈에 본다 (값은 모두 서버가 코드로 계산해 준다)
  const TREND_WORD = {
    "성공률": { up: "올랐어요", down: "내려갔어요", flat: "비슷해요", insufficient: "기록 더 필요" },
    "체감 난이도": { up: "쉬워졌어요", down: "어려워졌어요", flat: "비슷해요", insufficient: "기록 더 필요" },
  };

  function summaryValue(r) {
    if (!r.has_data) return h("td", { class: "muted" }, "기록 없음");
    if (!r.base_has_records) return h("td", { class: "muted" }, `이 주 기록 없음 · 마지막 기록 ${r.last_recorded_week.slice(5)}`);
    const parts = [];
    if (r.attempts > 0) parts.push(h("div", {}, `${r.rate}% (${r.makes}/${r.attempts}회)`, r.enough ? null : h("span", { class: "muted" }, " · 표본 적음")));
    if (r.rating_count > 0) parts.push(h("div", {}, `체감 ${r.rating_avg}점 (${r.rating_count}건)`));
    return h("td", {}, parts);
  }

  function summaryTrend(r) {
    if (r.trend_status === "none") return h("td", { class: "muted" }, "-");
    const word = (TREND_WORD[r.trend_kind] || {})[r.trend_status] || "";
    return h("td", { title: r.trend_text }, h("span", { class: "badge " + (TREND_CLASS[r.trend_status] || "") }, `${ARROW[r.trend_status]} ${word}`), h("span", { class: "muted" }, ` ${r.trend_kind}`));
  }

  // 방사형 차트(참고용): 분야마다 0~100 점수. 기준 주는 진한 면, 4주 전은 점선. 기록 없는 분야는 점을 찍지 않고 "기록 없음"으로 적는다.
  function radarChart(radar) {
    const W = 340, H = 320, cx = 170, cy = 158, R = 104, LABEL = 128;
    const n = radar.axes.length;
    const angle = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n; // 맨 위 축에서 시계 방향
    const at = (i, value) => [cx + Math.cos(angle(i)) * R * (value / 100), cy + Math.sin(angle(i)) * R * (value / 100)];
    const fmt = (p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`;
    const parts = [];
    [25, 50, 75, 100].forEach((v) => {
      parts.push(s("polygon", { class: "ring", points: radar.axes.map((_, i) => fmt(at(i, v))).join(" ") }));
      parts.push(s("text", { class: "ringtext", x: cx + 4, y: cy - (R * v) / 100 + 11 }, String(v)));
    });
    radar.axes.forEach((a, i) => {
      const end = at(i, 100);
      parts.push(s("line", { class: "axisline", x1: cx, y1: cy, x2: end[0], y2: end[1] }));
      const lx = cx + Math.cos(angle(i)) * LABEL;
      const ly = cy + Math.sin(angle(i)) * LABEL;
      const anchor = Math.abs(lx - cx) < 8 ? "middle" : lx > cx ? "start" : "end";
      parts.push(
        s("text", { class: "axislabel" + (a.current == null ? " nodata" : ""), x: lx, y: ly + 4, "text-anchor": anchor }, a.field),
        a.current == null ? s("text", { class: "axisnote", x: lx, y: ly + 18, "text-anchor": anchor }, "기록 없음") : null
      );
    });
    // 값이 있는 축만 이어서 면(3개 이상) 또는 선(2개)으로 그린다. 값이 없는 축은 0점으로 두지 않고 건너뛴다.
    const shape = (key, cls) => {
      const pts = radar.axes.map((a, i) => (a[key] == null ? null : at(i, a[key]))).filter(Boolean);
      if (pts.length >= 3) return s("polygon", { class: cls, points: pts.map(fmt).join(" ") });
      if (pts.length === 2) return s("polyline", { class: cls + " open", points: pts.map(fmt).join(" ") });
      return null;
    };
    parts.push(shape("previous", "area-prev"), shape("current", "area-current"));
    radar.axes.forEach((a, i) => {
      if (a.previous != null) parts.push(s("circle", { class: "dot-prev", cx: at(i, a.previous)[0], cy: at(i, a.previous)[1], r: 3.5 }));
    });
    radar.axes.forEach((a, i) => {
      if (a.current != null) parts.push(s("circle", { class: "dot-cur" + (a.current_thin ? " hollow" : ""), cx: at(i, a.current)[0], cy: at(i, a.current)[1], r: 5 }));
    });
    const label =
      "분야별 점수(0~100, 참고용): " +
      radar.axes.map((a) => `${a.field} ${a.current == null ? "기록 없음" : a.current + "점"}${a.previous == null ? "" : `(4주 전 ${a.previous}점)`}`).join(", ");
    return s("svg", { class: "radar", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label, preserveAspectRatio: "xMidYMid meet" }, s("title", {}, label), parts);
  }

  function radarBox(radar) {
    const box = h("div", { class: "radar-box" });
    if (radar.axes_with_data < radar.min_axes) {
      box.append(
        h("p", { class: "hint" }, `기준 주에 기록이 있는 분야가 ${radar.axes_with_data}개예요. ${radar.min_axes}개 이상이어야 방사형 차트로 그려져요.`)
      );
      return box;
    }
    box.append(
      h("p", { class: "chart-title" }, "분야별 점수 (방사형)", h("span", { class: "muted" }, " · 참고용")),
      radarChart(radar),
      h(
        "p",
        { class: "legend" },
        h("span", { class: "legend-cur" }, "●"),
        ` 기준 주 ${radar.base_week} `,
        radar.compare_week ? [h("span", { class: "legend-prev" }, "┄"), ` 4주 전 ${radar.compare_week}`] : h("span", { class: "muted" }, "· 4주 전 주가 보이는 기간 밖이라 비교선은 없어요")
      ),
      h("p", { class: "hint" }, "슛은 성공률(%), 그 밖의 분야는 체감 난이도를 0~100점으로 바꾼 값이에요(어려웠음 0 · 적당 50 · 쉬웠음 100). 속이 빈 점은 기록이 적어 참고만 해요.")
    );
    return box;
  }

  function summaryCard(summary, weekCount) {
    const head = ["분야", "기준 주 기록", "다음 주 난이도", "최근 추이", "기록 있는 주"];
    const body = summary.rows.map((r) =>
      h(
        "tr",
        {},
        h("th", { scope: "row" }, r.field),
        summaryValue(r),
        r.base_has_records ? verdictCell(r.verdicts) : h("td", { class: "muted" }, "-"),
        summaryTrend(r),
        h("td", {}, r.has_data ? `${r.recorded_weeks}/${weekCount}주` : "-")
      )
    );
    return h(
      "section",
      { class: "summary-card", "aria-label": "분야별 종합" },
      h("h3", {}, "한눈에 보기"),
      h(
        "p",
        { class: "hint" },
        `기준 주 ${summary.base_week} (${weekLabel(summary.base_week)})`,
        summary.is_current ? null : " · 이번 주 기록이 아직 없어서 기록이 있는 가장 최근 주를 기준으로 했어요."
      ),
      h(
        "div",
        { class: "summary-grid" },
        radarBox(summary.radar),
        h(
          "div",
          { class: "tablewrap" },
          h("table", { class: "summary-table" }, h("thead", {}, h("tr", {}, head.map((t) => h("th", { scope: "col" }, t)))), h("tbody", {}, body))
        )
      )
    );
  }

  function renderProgress(container, data) {
    const range = `${data.weeks[0]} ~ ${data.weeks[data.weeks.length - 1]}`;
    container.replaceChildren(
      h("div", { class: "board-head" }, h("h2", {}, "분야별 실력 현황"), h("span", { class: "muted" }, `최근 ${data.weeks.length}주 · ${range}`)),
      h(
        "p",
        { class: "hint" },
        "슛은 주별 성공률, 그 밖의 분야는 체감 난이도 평균(쉬웠음 3점·적당 2점·어려웠음 1점)이에요. 최근 4주와 그 앞 4주를 합쳐서 비교해요."
      )
    );
    if (!data.fields.some((f) => f.has_data)) {
      container.append(h("div", { class: "empty" }, "아직 기록이 없어요. 계획 화면에서 연습 기록을 입력하면 분야별 변화를 볼 수 있어요."));
      return;
    }
    container.append(summaryCard(data.summary, data.weeks.length), h("div", { class: "fields" }, data.fields.map(fieldCard)));
  }

  // ---- 본 화면 -----------------------------------------------------------------------
  async function renderMain() {
    const me = await api("/auth/me");
    whoName.textContent = me.username;
    who.hidden = false;
    document.querySelectorAll("dialog.cond-dialog").forEach((d) => d.remove()); // 다시 로그인할 때 팝업이 겹쳐 쌓이지 않게

    const state = { week: "", current: "", planWeeks: [] };
    const board = h("div", { class: "board-body" }); // 요일 띠와 고른 요일의 연습 목록(또는 만드는 중·초안·빈 화면)이 들어간다
    const weekHead = h("div", { class: "weekhead", "aria-label": "주 이동" });
    const isFuture = (week) => week > state.current; // 같은 형식의 주 값은 글자 비교가 곧 날짜 비교다

    // ---- 오른쪽 열: 내 조건, 이번 주 한눈에, 추천, 지난주 결과, 오늘의 농구 이야기 -------------------------------
    const condCard = h("section", { class: "rcard", "aria-label": "내 조건" });
    const glanceCard = h("section", { class: "rcard", hidden: true, "aria-label": "이번 주 한눈에" });
    const recoCard = h("section", { class: "rcard reco", hidden: true, "aria-label": "추천" });
    const lastCard = h("section", { class: "rcard", hidden: true, "aria-label": "지난주 결과" });
    const storyBox = h("aside", { class: "rcard story", hidden: true, "aria-label": "오늘의 농구 이야기" });
    const rail = h("aside", { class: "rail" }, condCard, glanceCard, recoCard, lastCard, storyBox);

    // "계획 만들기"를 누르면 이야기부터 받아 보여 준다. 이야기는 모델 없이 도착하므로 계획이 만들어지는 동안 기다리며 읽을 수 있다.
    async function showStory() {
      try {
        const story = await api("/story");
        storyBox.replaceChildren(h("h4", {}, "오늘의 농구 이야기"), h("p", {}, story.text));
        storyBox.hidden = false;
      } catch (error) {
        // 이야기를 받지 못해도 계획 만들기는 그대로 진행한다
      }
    }

    function chipsOf(input) {
      const list = [];
      list.push(input.is_beginner ? "농구 입문" : [input.position, input.level].filter(Boolean).join(" · "));
      list.push(`주 ${input.days_per_week}일 · ${input.minutes_per_session}분`);
      list.push((input.equipment || []).length ? input.equipment.join(" · ") : "공만");
      (input.goals || []).forEach((g) => list.push(g));
      return list.filter(Boolean).map((text) => h("span", { class: "chipx" }, text));
    }

    // 계획이 바뀔 때마다(그리기·초안·빈 화면) 오른쪽 열의 내용을 맞춘다
    hooks.planShown = (plan, mode) => {
      condCard.replaceChildren(
        h("h4", {}, "내 조건"),
        plan ? h("div", { class: "chipsx" }, chipsOf(plan.input || {})) : h("p", { class: "muted" }, "아직 이 주의 계획이 없어요."),
        h("button", { class: "linkbtn", type: "button", onclick: () => hooks.openForm() }, plan ? "조건 바꿔서 다시 만들기 →" : "조건을 입력하고 계획 만들기 →"),
        ...(plan && mode !== "draft" ? [h("button", { class: "linkbtn danger", type: "button", onclick: () => hooks.deletePlan(plan) }, "이 주 계획 삭제")] : []) // 비어 있으면 아예 넘기지 않는다(null을 넘기면 "null" 글자가 들어간다)
      );
      glanceCard.hidden = true; // 기록을 불러온 뒤 stats가 채운다 (초안·미래 주에는 없다)
      const last = (plan && plan.last_week) || [];
      lastCard.hidden = !last.length;
      lastCard.replaceChildren(
        ...(last.length
          ? [
              // 처음에는 제목만 보이고, 펼치면 메뉴별 판정과 이유가 보인다
              h(
                "details",
                { class: "lastweek" },
                h("summary", {}, `지난주 결과가 이번 계획에 반영됐어요 (연습 메뉴 ${last.length}개)`),
                h("ul", {}, last.map((j) => h("li", {}, h("strong", {}, j.drill), verdictBadge(j.verdict), h("span", { class: "muted" }, j.reason))))
              ),
            ]
          : [])
      );
      const recs = (plan && plan.recommendations) || [];
      recoCard.hidden = !recs.length;
      recoCard.replaceChildren(
        ...(recs.length
          ? [
              // 올릴 곳이 없는 상향: 그 메뉴는 계획에 유지하고, 규칙으로 고른 다른 분야 메뉴를 추천한다
              h("h4", {}, "다른 분야 연습을 추천해요"),
              h("ul", {}, recs.map((r) => h("li", {}, h("strong", {}, r.menu), h("span", { class: "lv" }, `${r.field} · ${r.difficulty}`), h("span", { class: "muted" }, r.text)))),
            ]
          : [])
      );
    };
    hooks.stats = (s) => {
      glanceCard.hidden = !s;
      if (!s) return;
      const v = s.verdicts;
      const row = (label, value) => h("div", { class: "stat" }, h("span", {}, label), h("b", {}, value));
      glanceCard.replaceChildren(
        h("h4", {}, "이번 주 한눈에"),
        row("기록", `${s.saved} / ${s.total}`),
        row("완료한 요일", `${s.daysDone} / ${s.daysTotal}`),
        row("다음 주 난이도", v.상향 + v.유지 + v.하향 ? `상향 ${v.상향} · 유지 ${v.유지} · 하향 ${v.하향}` : "기록하면 나와요")
      );
    };
    hooks.currentWeek = () => state.current;

    // ---- 주 이동 (위쪽): ‹ 46주 › / 주 선택 / 이번 주 / 계획 있는 주 바로가기 -----------------------------------
    function drawWeekBar() {
      const offset = weeksBetween(state.week, state.current);
      const go = (week) => () => select(week);
      const prev = h("button", { class: "arrow", type: "button", "aria-label": "이전 주", disabled: offset <= -WEEK_RANGE, onclick: go(shiftWeek(state.week, -1)) }, "‹");
      const next = h("button", { class: "arrow", type: "button", "aria-label": "다음 주", disabled: offset >= WEEK_RANGE, onclick: go(shiftWeek(state.week, 1)) }, "›");
      const today = h("button", { class: "ghost", type: "button", disabled: offset === 0, onclick: go(state.current) }, "이번 주");
      const input = h("input", {
        type: "week", id: "week-input", value: state.week,
        min: shiftWeek(state.current, -WEEK_RANGE), max: shiftWeek(state.current, WEEK_RANGE),
        onchange: () => {
          const value = input.value;
          const ok = weekMonday(value) && Math.abs(weeksBetween(value, state.current)) <= WEEK_RANGE;
          if (ok) select(value);
          else input.value = state.week; // 형식이 틀리거나 범위 밖이면 원래 주로 되돌린다
        },
      });
      const kind = state.week === state.current ? "이번 주" : isFuture(state.week) ? "앞으로 올 주" : "지난 주";
      const hasPlan = state.planWeeks.includes(state.week);
      const chips = state.planWeeks.slice(-12).map((week) =>
        h("button", { class: "weekchip", type: "button", "aria-current": week === state.week ? "true" : false, onclick: go(week) }, week.slice(5))
      );
      weekHead.replaceChildren(
        h(
          "div",
          { class: "head" },
          prev,
          h("h1", {}, `${Number(state.week.slice(6))}주`, h("small", {}, `${state.week.slice(0, 4)}년 · ${weekLabel(state.week)} · ${kind}`)),
          next,
          h("span", { class: "badge " + (hasPlan ? "up" : "") }, hasPlan ? "계획 있음" : "계획 없음"),
          h("span", { class: "spacer" }),
          h("label", { class: "weekpick", for: "week-input" }, "주 선택", input),
          today
        ),
        ...(chips.length ? [h("div", { class: "weekchips", "aria-label": "계획이 있는 주" }, h("span", { class: "muted" }, "계획이 있는 주"), chips)] : [])
      ); // replaceChildren·append에 null을 넘기면 "null"이라는 글자가 들어가므로 비어 있으면 아예 넘기지 않는다
    }

    async function loadWeeks() {
      const info = await api("/plans/weeks");
      state.current = info.current;
      state.planWeeks = info.weeks;
      form.setFirstPlan(info.weeks.length === 0); // 계획이 하나도 없을 때만 입문 선택을 보인다
    }

    // 고른 주의 계획을 불러와 보드에 그린다. 그 사이 다른 주로 옮겼으면 이 결과는 버린다.
    async function select(week) {
      state.week = week;
      storyBox.hidden = true; // 이야기는 "계획 만들기"를 누른 때부터 보인다
      drawWeekBar();
      board.replaceChildren(h("div", { class: "loading", role: "status" }, "불러오는 중이에요."));
      const plan = await api("/plans/current?week=" + encodeURIComponent(week)).catch(() => null);
      if (state.week !== week) return;
      if (plan) form.fill(plan.input);
      await showPlan(board, plan, isFuture(week) ? "future" : "");
    }

    // ---- 조건 입력 팝업(장소·장비 골대·콘·벽 포함) ----------------------------------------------------------
    const form = buildForm(async (body) => {
      const week = state.week;
      body.week = week;
      if (condDialog.open) condDialog.close(); // 만드는 동안은 팝업을 닫고 이야기와 진행 표시를 보여 준다
      showStory(); // 기다리지 않는다: 계획 요청과 함께 바로 시작한다
      board.replaceChildren(generatingPanel());
      let result;
      try {
        result = await api("/plans", { method: "POST", body });
      } catch (error) {
        const previous = await api("/plans/current?week=" + encodeURIComponent(week)).catch(() => null);
        await showPlan(board, previous, isFuture(week) ? "future" : "");
        hooks.openForm(); // 입력 오류는 팝업의 안내로 다시 보여 준다
        throw error;
      }
      if (state.week !== week) return; // 만드는 동안 다른 주로 옮겼다. 초안은 24시간 뒤 사라진다
      if (result.status === "pending") {
        const afterDecision = async (outcome, plan) => {
          if (outcome === "redo") return form.submit(); // 같은 조건으로 새 초안
          if (outcome === "confirmed") {
            await loadWeeks();
            drawWeekBar();
            return showPlan(board, plan, isFuture(week) ? "future" : "");
          }
          await showPlan(board, await api("/plans/current?week=" + encodeURIComponent(week)).catch(() => null), isFuture(week) ? "future" : ""); // 만료·없어진 초안
          board.prepend(h("p", { class: "msg", role: "alert" }, "초안이 만료됐거나 없어졌어요. 조건을 확인하고 다시 만들어 주세요."));
        };
        showDraft(board, result, body, afterDecision);
      } else {
        board.replaceChildren(
          h("p", { class: "msg", role: "alert" }, result.message),
          h("ul", {}, (result.violations || []).map((v) => h("li", {}, v))),
          h("button", { class: "save big", type: "button", onclick: () => hooks.openForm() }, "조건을 바꿔서 다시 만들기")
        );
      }
    });
    const condDialog = h(
      "dialog",
      { class: "cond-dialog", "aria-label": "내 조건" },
      h("button", { class: "dlg-close", type: "button", "aria-label": "닫기", onclick: () => condDialog.close() }, "✕"),
      form.node
    );
    document.body.append(condDialog);
    hooks.openForm = () => {
      if (!condDialog.open) condDialog.showModal();
    };

    // 주별 계획 삭제: 지워질 기록 건수를 보여 주는 팝업에서 확인을 받은 뒤에만 지운다.
    hooks.deletePlan = async (plan) => {
      const week = plan.week;
      const rows = isFuture(week) ? [] : await api("/records/week?week=" + encodeURIComponent(week)).catch(() => []);
      const n = rows.reduce((sum, r) => sum + r.shots.length + r.ratings.length, 0);
      const yes = await confirmDialog({
        title: "이 주 계획을 삭제할까요?",
        lines: [
          `${week} (${weekLabel(week)}) 주의 계획을 삭제해요.`,
          n ? `그 주에 입력한 기록 ${n}건도 함께 지워져요.` : "그 주에 입력한 기록은 없어요.",
          "삭제하면 되돌릴 수 없어요.",
        ],
        okText: n ? `계획과 기록 ${n}건 삭제` : "계획 삭제",
      });
      if (!yes) return;
      try {
        const done = await api("/plans?week=" + encodeURIComponent(week), { method: "DELETE" });
        await loadWeeks(); // 주 목록과 "처음 시작했어요" 선택도 다시 맞춘다
        drawWeekBar();
        await select(state.week);
        board.prepend(h("p", { class: "msg info", role: "status" }, `삭제했어요. (기록 ${done.deleted_records}건 함께 삭제)`));
      } catch (error) {
        await loadWeeks();
        drawWeekBar();
        await select(state.week);
        board.prepend(h("p", { class: "msg", role: "alert" }, error.message));
      }
    };

    // ---- 위쪽 메뉴: 주간 계획 / 분야별 현황. 현황은 메뉴를 열 때마다 새로 불러온다. ------------------------------
    const planView = h("div", { class: "wrap" }, h("section", { class: "main-col" }, weekHead, board), rail);
    const progressView = h("section", { class: "wrap-single progress", hidden: true });
    const planTab = h("button", { class: "tab", type: "button", role: "tab", "aria-selected": "true" }, "주간 계획");
    const progressTab = h("button", { class: "tab", type: "button", role: "tab", "aria-selected": "false" }, "분야별 현황");
    const showTab = async (name) => {
      const progressOn = name === "progress";
      planTab.setAttribute("aria-selected", String(!progressOn));
      progressTab.setAttribute("aria-selected", String(progressOn));
      planView.hidden = progressOn;
      progressView.hidden = !progressOn;
      if (!progressOn) return;
      progressView.replaceChildren(h("div", { class: "loading", role: "status" }, "불러오는 중이에요."));
      try {
        renderProgress(progressView, await api("/progress?weeks=8"));
      } catch (error) {
        progressView.replaceChildren(h("p", { class: "msg", role: "alert" }, error.message));
      }
    };
    planTab.addEventListener("click", () => showTab("plan"));
    progressTab.addEventListener("click", () => showTab("progress"));
    navEl.replaceChildren(planTab, progressTab);
    navEl.hidden = false;
    app.replaceChildren(planView, progressView);
    await loadWeeks();
    await select(state.current);
  }

  async function boot() {
    try {
      await renderMain();
    } catch (error) {
      if (error.status === 401) renderAuth();
      else app.replaceChildren(h("p", { class: "msg", role: "alert" }, error.message));
    }
  }

  logoutBtn.addEventListener("click", async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => null);
    renderAuth();
  });

  boot();
})();
