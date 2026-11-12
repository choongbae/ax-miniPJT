"""검색 결과를 계획 생성에 연결하는 흐름 테스트 (가짜 임베딩 사용)."""
from src.agent import available_drills, build_query, run_agent, select_menus
from src.models import UserInput, WeeklyPlan
from src.tools import DrillJudgment, load_drills

CATALOG = load_drills()


def make_user(equipment, goals=None, level="중급", beginner=False, position="가드"):
    return UserInput(
        position="미정" if beginner else position,
        level="초급" if beginner else level,
        is_beginner=beginner,
        goals=goals or [],
        days_per_week=3,
        minutes_per_session=40,
        equipment=equipment,
    )


def names(menus):
    return {m.name for m in menus}


def test_query_includes_level_position_and_goals():
    q = build_query(make_user(["골대"], goals=["3점슛", "왼손 드리블"]))
    assert "중급" in q and "가드" in q and "3점슛" in q and "왼손 드리블" in q


def test_query_for_beginner_skips_undecided_position_and_mentions_basics():
    q = build_query(make_user([], beginner=True))
    assert "미정" not in q and "처음 시작" in q and "초급" in q


def test_selected_menus_respect_equipment_case9(retriever):
    menus, _ = select_menus(make_user([], goals=["3점슛"]), CATALOG, retriever)
    assert menus and not any(m.is_shooting or m.requires for m in menus)  # 골대 없음 -> 슛·장비 메뉴 없음


def test_selected_menus_for_beginner_are_beginner_level_only_case26(retriever):
    menus, contexts = select_menus(make_user(["골대", "콘"], beginner=True), CATALOG, retriever)
    assert menus and all(m.difficulty == "초급" for m in menus)
    assert contexts and all(c.keys() == {"doc_id", "text"} for c in contexts)


def test_search_candidates_match_user_level_or_one_below(retriever):
    allowed = {"초급": {"초급"}, "중급": {"초급", "중급"}, "상급": {"중급", "상급"}}
    for level, ok in allowed.items():
        menus, _ = select_menus(make_user(["골대", "콘", "벽"], level=level), CATALOG, retriever)
        assert menus and {m.difficulty for m in menus} <= ok, level


def test_harder_menus_come_only_from_a_raise_judgment(retriever):
    user = make_user(["골대", "콘"], goals=["3점슛"])
    plain, _ = select_menus(user, CATALOG, retriever)
    assert not any(m.difficulty == "상급" for m in plain)
    raise_ = DrillJudgment("3점 캐치앤슛", "상향", "성공률 70.0% -> 상향")
    raised, _ = select_menus(user, CATALOG, retriever, [raise_])
    assert any(m.difficulty == "상급" for m in raised)


def test_selected_menu_count_is_limited_by_k(retriever):
    menus, contexts = select_menus(make_user(["골대", "콘", "벽"]), CATALOG, retriever, k=5)
    assert len(contexts) == 5 and len(menus) == 5


def test_judged_menus_and_candidates_are_included_even_if_not_retrieved(retriever):
    user = make_user(["골대", "콘"], goals=["왼손 드리블"])
    lower = DrillJudgment("3점 캐치앤슛", "하향", "성공률 20.0% -> 하향")
    carry = DrillJudgment("양손 레이업", "유지", "기록 없음", carry_over=True)
    menus, contexts = select_menus(user, CATALOG, retriever, [lower, carry], k=2)
    got = names(menus)
    assert {"양손 레이업", "3점 캐치앤슛"} <= got  # 판정에 나온 메뉴
    assert {"제자리 자유투", "미드레인지 제자리 점프슛"} <= got  # 하향 후보
    assert len(contexts) == 2  # contexts는 실제 검색 결과만


def test_menus_never_include_unavailable_ones_even_from_judgments(retriever):
    user = make_user([], goals=["드리블"])  # 공만 있음
    raise_ = DrillJudgment("3점 캐치앤슛", "상향", "성공률 70.0% -> 상향")
    menus, _ = select_menus(user, CATALOG, retriever, [raise_])
    assert not any(m.requires for m in menus)


def test_graph_retrieve_step_passes_selected_menus_to_generator(retriever):
    seen = {}
    plan = WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": "3점 캐치앤슛", "sets": 3, "reps": 10, "minutes": 20, "purpose": "p"}]}]}
    )

    def fake(user, catalog, violations, judgments=None, menus=None):
        seen["menus"] = menus
        return plan

    state = run_agent(make_user(["골대", "콘"], goals=["3점슛"]), CATALOG, generate_fn=fake, retriever=retriever)
    assert seen["menus"] and names(seen["menus"]) <= names(available_drills(make_user(["골대", "콘"]), CATALOG))
    assert state["contexts"] and state["menus"] == seen["menus"]
    assert any(line.startswith("검색:") for line in state["log"])


def test_graph_without_retriever_uses_all_available_menus():
    seen = {}
    plan = WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": "제자리 볼 핸들링", "sets": 3, "reps": 10, "minutes": 20, "purpose": "p"}]}]}
    )

    def fake(user, catalog, violations, judgments=None, menus=None):
        seen["menus"] = menus
        return plan

    user = make_user([])
    state = run_agent(user, CATALOG, generate_fn=fake)
    assert names(seen["menus"]) == names(available_drills(user, CATALOG))
    assert state["contexts"] == []


def test_search_failure_falls_back_to_all_menus_and_keeps_going():
    class Broken:
        def search(self, *args, **kwargs):
            raise RuntimeError("임베딩 호출 실패")

    seen = {}
    plan = WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": "제자리 볼 핸들링", "sets": 3, "reps": 10, "minutes": 20, "purpose": "p"}]}]}
    )

    def fake(user, catalog, violations, judgments=None, menus=None):
        seen["menus"] = menus
        return plan

    user = make_user([])
    state = run_agent(user, CATALOG, generate_fn=fake, retriever=Broken())
    assert state["status"] == "ok"
    assert names(seen["menus"]) == names(available_drills(user, CATALOG))
    assert any("검색 실패(RuntimeError)" in line for line in state["log"])
