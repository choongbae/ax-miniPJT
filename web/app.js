"use strict";
/* 농구 연습 계획 화면. 서버가 준 글(계획, 안내, 이야기)은 모델이 만든 것이라 innerHTML을 쓰지 않고 textContent로만 그린다. */
(function () {
  const app = document.getElementById("app");
  const who = document.getElementById("who");
  const whoName = document.getElementById("who-name");
  const logoutBtn = document.getElementById("logout");

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

  // 한 연습 메뉴의 기록 입력칸. update(info)로 이번 주 합계와 다음 주 난이도 예고를 다시 그린다.
  function recordBox(drill, onSaved, week) {
    const state = h("p", { class: "savestate" }); // 저장 상태를 늘 보여 준다: 기록 없음 / 입력 중(저장 안 됨) / 저장됨 N건
    const flash = h("p", { class: "flash", role: "status" }); // 저장 직후 잠깐 나오는 확인 문구 (스크린리더에도 읽힌다)
    const status = h("p", { class: "done" });
    const result = h("div", { class: "result", "aria-live": "polite" });
    const errorBox = h("div");
    const submit = h("button", { class: "btn small", type: "submit" }, "기록 저장");
    let fields;
    let readBody;
    let isDirty;
    let savedCount = 0;
    let dirty = false;
    let flashTimer = null;

    const drawState = () => {
      state.className = "savestate " + (dirty ? "dirty" : savedCount ? "saved" : "none");
      state.textContent = dirty ? "✎ 입력 중 · 아직 저장 안 됨" : savedCount ? `✓ 저장됨 · ${savedCount}건` : "기록 없음";
    };
    const showFlash = (text) => {
      if (flashTimer) clearTimeout(flashTimer);
      flash.textContent = text;
      flashTimer = setTimeout(() => { flash.textContent = ""; }, 6000);
    };

    if (drill.is_shooting) {
      const attempts = h("input", { type: "number", min: 1, inputmode: "numeric" });
      const makes = h("input", { type: "number", min: 0, inputmode: "numeric" });
      fields = h(
        "div",
        { class: "inline" },
        h("label", { class: "field" }, "시도", attempts),
        h("label", { class: "field" }, "성공", makes)
      );
      isDirty = () => attempts.value !== "" || makes.value !== "";
      readBody = () => {
        const a = Number(attempts.value);
        const m = Number(makes.value);
        if (attempts.value === "" || makes.value === "") return { error: "시도와 성공 횟수를 입력해 주세요." };
        if (!Number.isInteger(a) || a < 1) return { error: "시도 수는 1 이상의 정수여야 해요." };
        if (!Number.isInteger(m) || m < 0) return { error: "성공 수는 0 이상의 정수여야 해요." };
        if (m > a) return { error: `성공 수(${m})가 시도 수(${a})보다 많을 수 없어요.` };
        return {
          body: { drill: drill.name, shots: [{ attempts: a, makes: m }] },
          summary: `${a}회 중 ${m}회`,
          reset: () => { attempts.value = ""; makes.value = ""; },
        };
      };
    } else {
      const group = drill.name + "-" + Math.random().toString(36).slice(2, 7);
      fields = h("div", { class: "chips", role: "radiogroup", "aria-label": `${drill.name} 체감 난이도` }, RATINGS.map((r) => chip("radio", group, r, r, false)));
      isDirty = () => !!fields.querySelector("input:checked");
      readBody = () => {
        const checked = fields.querySelector("input:checked");
        if (!checked) return { error: "쉬웠음, 적당, 어려웠음 중 하나를 골라 주세요." };
        return { body: { drill: drill.name, ratings: [checked.value] }, summary: checked.value, reset: () => { checked.checked = false; } };
      };
    }

    const form = h(
      "form",
      {
        class: "record",
        novalidate: true,
        onsubmit: async (event) => {
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
            await api("/records", { method: "POST", body: { ...parsed.body, week } });
            parsed.reset();
            dirty = false;
            showFlash(`✓ 저장했어요 (${parsed.summary})`);
            await onSaved(); // 같은 메뉴가 여러 날 있는 카드까지 합계와 저장 건수를 다시 그린다
          } catch (error) {
            showFlash("");
            showError(errorBox, error.message + " (저장되지 않았어요)");
          } finally {
            submit.disabled = false;
            submit.textContent = "기록 저장";
            drawState();
          }
        },
      },
      state,
      status,
      result,
      fields,
      errorBox,
      flash,
      submit
    );
    const refreshDirty = () => {
      dirty = isDirty();
      drawState();
    };
    form.addEventListener("input", refreshDirty);
    form.addEventListener("change", refreshDirty);
    drawState();

    function update(info) {
      status.replaceChildren();
      result.replaceChildren();
      savedCount = info ? info.shots.length + info.ratings.length : 0;
      drawState();
      form.classList.toggle("saved", savedCount > 0);
      if (!info) return;
      if (drill.is_shooting && info.shots.length) {
        const tried = info.shots.reduce((sum, s) => sum + s.attempts, 0);
        const made = info.shots.reduce((sum, s) => sum + s.makes, 0);
        status.append(`이 주 기록 ${info.shots.map((s) => `${s.attempts}회 중 ${s.makes}회`).join(", ")} (합계 ${tried}회 중 ${made}회)`);
      } else if (!drill.is_shooting && info.ratings.length) {
        const counts = RATINGS.map((r) => [r, info.ratings.filter((x) => x === r).length]).filter(([, n]) => n > 0);
        status.append("이 주 평가 " + counts.map(([r, n]) => `${r} ${n}번`).join(", "));
      }
      if (info.carry_over) {
        result.append(verdictBadge("유지", "다음 주 난이도 유지"), h("span", { class: "muted" }, "기록이 없으면 다음 주 계획에 같은 연습을 다시 넣어요."));
      } else {
        result.append(verdictBadge(info.verdict, "다음 주 난이도 " + info.verdict), h("span", { class: "muted" }, info.reason));
      }
    }
    return { node: form, update };
  }

  // ---- 주간 보드 ---------------------------------------------------------------------
  function drillCard(drill, registry, onSaved, week) {
    const box = onSaved ? recordBox(drill, onSaved, week) : null; // 초안과 아직 오지 않은 주에는 기록칸이 없다
    if (box) registry.push({ name: drill.name, update: box.update });
    return h(
      "article",
      { class: "drill" },
      h("h4", {}, drill.name, h("span", { class: "badge" }, drill.difficulty), drill.is_shooting ? h("span", { class: "badge" }, "슛") : null),
      h("p", { class: "dose" }, `${drill.sets}세트 × ${drill.reps}회 · ${drill.minutes}분`),
      h("p", { class: "purpose" }, drill.purpose),
      drill.tip || drill.mistake
        ? h(
            "details",
            {},
            h("summary", {}, "자세 팁과 흔한 실수"),
            drill.tip ? h("p", {}, "자세 팁: " + drill.tip) : null,
            drill.mistake ? h("p", {}, "흔한 실수: " + drill.mistake) : null
          )
        : null,
      box ? box.node : null
    );
  }

  // 보드를 그리고, 기록 정보를 다시 반영하는 update(rows)를 돌려준다.
  // mode: "draft"(승인 대기 초안) | "future"(아직 오지 않은 주) | ""(기록을 입력할 수 있는 주). 앞의 둘은 기록칸이 없다.
  function renderBoard(container, plan, mode) {
    const preview = !!mode;
    container.replaceChildren();
    const registry = [];
    const update = (rows) => {
      const byName = new Map((rows || []).map((row) => [row.drill, row]));
      registry.forEach((entry) => entry.update(byName.get(entry.name)));
    };
    if (!plan) {
      container.append(h("div", { class: "empty" }, "이 주에는 아직 계획이 없어요. 왼쪽에서 조건을 입력하고 '계획 만들기'를 눌러 주세요."));
      return { update };
    }
    const refresh = preview ? null : async () => update(await api("/records/week?week=" + encodeURIComponent(plan.week)));

    const input = plan.input || {};
    const summary = [
      input.is_beginner ? "농구 입문" : `${input.position || ""} ${input.level || ""}`.trim(),
      `주 ${input.days_per_week}일`,
      `회당 ${input.minutes_per_session}분`,
      (input.equipment || []).length ? (input.equipment || []).join("·") : "공만",
    ].join(" · ");

    container.append(
      h(
        "div",
        { class: "board-head" },
        h("h2", {}, mode === "draft" ? "계획 초안" : "주간 계획"),
        h("span", { class: "muted" }, `${plan.week} (${weekLabel(plan.week)})`),
        // 확정된 계획에만 삭제 버튼이 있다 (초안은 확정하지 않으면 저장되지 않으니 삭제할 것이 없다)
        mode !== "draft" && hooks.deletePlan
          ? h("button", { class: "btn quiet-danger small", type: "button", onclick: () => hooks.deletePlan(plan) }, "이 주 계획 삭제")
          : null
      ),
      h("p", { class: "summary" }, summary)
    );
    if (mode === "future") {
      container.append(h("p", { class: "hint" }, "아직 오지 않은 주예요. 계획만 등록할 수 있고, 기록은 연습한 뒤에 입력해 주세요."));
    } else if (!preview) {
      container.append(
        h("p", { class: "hint" }, "연습한 뒤 각 연습 아래에 기록하면, 이 주의 합계로 다음 주 난이도가 정해져요. 같은 연습이 여러 날 있으면 합계로 계산해요.")
      );
    }

    if ((plan.last_week || []).length) {
      container.append(
        h(
          "section",
          { class: "banner" },
          h("h3", {}, "지난주 결과가 이번 계획에 반영됐어요"),
          h(
            "ul",
            {},
            plan.last_week.map((j) =>
              h("li", {}, h("strong", {}, j.drill), verdictBadge(j.verdict), h("span", { class: "muted" }, j.reason))
            )
          )
        )
      );
    }
    if ((plan.recommendations || []).length) {
      // 올릴 곳이 없는 상향: 그 메뉴는 계획에 유지하고, 규칙으로 고른 다른 분야 메뉴를 추천한다
      container.append(
        h(
          "section",
          { class: "banner reco" },
          h("h3", {}, "다른 분야 연습을 추천해요"),
          h(
            "ul",
            {},
            plan.recommendations.map((r) =>
              h("li", {}, h("strong", {}, r.menu), h("span", { class: "badge" }, `${r.field} · ${r.difficulty}`), h("span", { class: "muted" }, r.text))
            )
          )
        )
      );
    }
    (plan.notices || []).forEach((text) => container.append(h("p", { class: "notice" }, text)));

    container.append(
      h(
        "div",
        { class: "days" },
        plan.days.map((day) =>
          h(
            "section",
            { class: "day" },
            h("h3", {}, day.day + "요일", h("span", {}, `${day.total_minutes}분`)),
            day.drills.map((drill) => drillCard(drill, registry, refresh, plan.week))
          )
        )
      )
    );

    (plan.history || []).forEach((story) =>
      container.append(h("aside", { class: "story" }, h("h3", {}, "오늘의 농구 이야기"), h("p", {}, story)))
    );
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
    container.append(h("div", { class: "fields" }, data.fields.map(fieldCard)));
  }

  // ---- 본 화면 -----------------------------------------------------------------------
  async function renderMain() {
    const me = await api("/auth/me");
    whoName.textContent = me.username;
    who.hidden = false;

    const state = { week: "", current: "", planWeeks: [] };
    const board = h("section", { class: "card board" });
    const weekBar = h("section", { class: "card weekbar", "aria-label": "주 이동" });
    const isFuture = (week) => week > state.current; // 같은 형식의 주 값은 글자 비교가 곧 날짜 비교다

    async function loadWeeks() {
      const info = await api("/plans/weeks");
      state.current = info.current;
      state.planWeeks = info.weeks;
      form.setFirstPlan(info.weeks.length === 0); // 계획이 하나도 없을 때만 입문 선택을 보인다
    }

    // 고른 주의 계획을 불러와 보드에 그린다. 그 사이 다른 주로 옮겼으면 이 결과는 버린다.
    async function select(week) {
      state.week = week;
      drawWeekBar();
      board.replaceChildren(h("div", { class: "loading", role: "status" }, "불러오는 중이에요."));
      const plan = await api("/plans/current?week=" + encodeURIComponent(week)).catch(() => null);
      if (state.week !== week) return;
      if (plan) form.fill(plan.input);
      await showPlan(board, plan, isFuture(week) ? "future" : "");
    }

    function drawWeekBar() {
      const offset = weeksBetween(state.week, state.current);
      const go = (week) => () => select(week);
      const prev = h("button", { class: "btn ghost small", type: "button", disabled: offset <= -WEEK_RANGE, onclick: go(shiftWeek(state.week, -1)) }, "‹ 이전 주");
      const next = h("button", { class: "btn ghost small", type: "button", disabled: offset >= WEEK_RANGE, onclick: go(shiftWeek(state.week, 1)) }, "다음 주 ›");
      const today = h("button", { class: "btn ghost small", type: "button", disabled: offset === 0, onclick: go(state.current) }, "이번 주");
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
      weekBar.replaceChildren(
        h("div", { class: "weekrow" }, prev, h("label", { class: "weekpick", for: "week-input" }, "주 선택", input), next, today),
        h(
          "p",
          { class: "weekinfo" },
          h("strong", {}, `${state.week} (${weekLabel(state.week)})`),
          h("span", { class: "badge" }, kind),
          h("span", { class: "badge " + (hasPlan ? "up" : "") }, hasPlan ? "계획 있음" : "계획 없음"),
          isFuture(state.week) ? h("span", { class: "muted" }, "기록은 연습한 뒤에 입력할 수 있어요") : null
        ),
        chips.length ? h("div", { class: "weekchips", "aria-label": "계획이 있는 주" }, h("span", { class: "muted" }, "계획이 있는 주"), chips) : null
      );
    }

    const form = buildForm(async (body) => {
      const week = state.week;
      body.week = week;
      board.replaceChildren(h("div", { class: "loading", role: "status" }, "계획을 만드는 중이에요. 20초쯤 걸려요."));
      let result;
      try {
        result = await api("/plans", { method: "POST", body });
      } catch (error) {
        const previous = await api("/plans/current?week=" + encodeURIComponent(week)).catch(() => null);
        await showPlan(board, previous, isFuture(week) ? "future" : "");
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
          h("ul", {}, (result.violations || []).map((v) => h("li", {}, v)))
        );
      }
    });

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

    // 위쪽 탭: 주간 계획 / 분야별 현황. 현황은 탭을 열 때마다 새로 불러온다.
    const planView = h("div", { class: "stack" }, weekBar, h("div", { class: "layout" }, form.node, board));
    const progressView = h("section", { class: "card progress", hidden: true });
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
    app.replaceChildren(h("div", { class: "stack" }, h("div", { class: "tabs main-tabs", role: "tablist", "aria-label": "화면 선택" }, planTab, progressTab), planView, progressView));
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
