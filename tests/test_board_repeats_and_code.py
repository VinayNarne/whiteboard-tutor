"""Two fixes from the owner's own Selenium lesson (2026-11-05): a block that repeats the board is refused (one diagram was drawn three
times under three titles, and a note was written twice), and code has its own block (asked for code, the learner got another diagram)."""
import re

import pytest
from unittest.mock import patch

from engine.scene import CODE_CHAR, CODE_PAD, NOTE_LANE, WIDE_LANE, SceneError, build_diagram, build_notes, normalise, prefix_ids, repeats
from test_scene import SCENE, _fake_tts, _model, needs_elk


def _board(*blocks):
    svg, placed = "", []
    for n, (kind, args) in enumerate(blocks, 1):
        if kind == "notes":
            steps, box, _ = build_notes(args, n, placed)
        else:
            steps, box, _ = build_diagram(prefix_ids(normalise(args), f"b{n}_"), n, placed)
        svg += "".join("\n" + f for _, f, _ in steps)
        placed.append(box)
    return svg


NOTES = {"title": "What is Selenium?", "lines": [{"text": "**Selenium** is a tool for automating web browsers"},
                                                {"text": "With Python you can write scripts to control Chrome"}]}


@needs_elk
def test_a_diagram_that_repeats_one_on_the_board_is_refused():
    svg = _board(("diagram", SCENE))
    again = {**SCENE, "title": "The same, renamed"}
    why = repeats("draw_scene", again, svg)
    assert "repeats block 1" in why and "annotate_element" in why
    other = {**SCENE, "nodes": [{**n, "label": f"Thing {i}"} for i, n in enumerate(SCENE["nodes"])]}
    assert repeats("draw_scene", other, svg) == ""                               # a different diagram is fine
    listed = _board(("notes", {"lines": [{"text": f"{n['label']} step"} for n in SCENE["nodes"]]}))
    assert repeats("draw_scene", SCENE, listed) == ""                             # notes listed the parts first: the diagram still may show them


def test_note_lines_that_repeat_the_board_are_refused_and_recaps_and_code_are_not():
    svg = _board(("notes", NOTES))
    dup = {"lines": [{"text": "Selenium lets you automate web browsers using Python"}, {"text": "Locators find elements by id or name"}]}
    why = repeats("write_notes", dup, svg)
    assert "Selenium lets you automate web browsers" in why and "Locators" not in why
    assert repeats("write_notes", {"lines": [{"text": "Locators find elements by **id** or name"}]}, svg) == ""
    assert "Python scripts" in repeats("write_notes", {"lines": [{"text": "**Python** scripts"}]}, svg)   # live: 'What You Need' restated setup
    assert repeats("write_notes", {"lines": [{"text": "Python decorators"}]}, svg) == ""
    assert repeats("write_notes", {**dup, "style": "recap"}, svg) == ""
    card = _board(("notes", {"style": "recap", "lines": [{"text": "Plants need sunlight, water, and carbon dioxide."}]}))
    again = {"style": "recap", "lines": [{"text": "Plants need sunlight, water and carbon dioxide."}]}
    assert "already on the board" in repeats("write_notes", again, card)                    # live: a second, near-identical recap card
    assert repeats("write_notes", {**dup, "style": "code"}, svg) == ""
    script = {"style": "code", "lines": [{"text": "from selenium import webdriver\ndriver = webdriver.Chrome()", "say": "a"},
                                         {"text": "driver.get('https://example.com')", "say": "b"}]}
    with_code = _board(("notes", script))
    assert "already on the board" in repeats("write_notes", script, with_code)                  # live: the same script drawn twice
    longer = {**script, "lines": script["lines"][:1] + [{"text": "box = driver.find_element(By.ID, 'q')", "say": "c"},
                                                        {"text": "box.send_keys('hello')", "say": "d"}]}
    assert repeats("write_notes", longer, with_code) == ""                                     # a new script that reuses its imports
    assert repeats("write_notes", dup, None) == ""                                # an empty board repeats nothing


def test_code_card_keeps_spacing_escapes_wraps_and_picks_its_lane():
    code = {"style": "code", "title": "open_page.py", "lines": [
        {"text": "from selenium import webdriver\ndriver = webdriver.Chrome()", "say": "Import Selenium and start Chrome."},
        {"text": "if x < 3:\n    driver.get('https://example.com')", "say": "Open the page."}]}
    steps, box, report = build_notes(code, 1, [])
    assert report == {"kind": "code", "lines": 4} and box["w"] == NOTE_LANE[1] and len(steps) == 2
    frag = steps[1][1]
    assert "    driver.get(" in frag and "x &lt; 3:" in frag      # indentation kept, < escaped
    assert "driver" not in steps[0][2] and steps[0][2].endswith("Import Selenium and start Chrome.")   # never read aloud
    longest = "x = " + "1 + " * 40
    wide, wbox, _ = build_notes({"style": "code", "lines": [{"text": longest, "say": "A long sum."}]}, 2, [box])
    assert wbox["w"] == WIDE_LANE[1] and wbox["y"] > box["y"] + box["h"]
    per_row = int((WIDE_LANE[1] - 2 * CODE_PAD) / CODE_CHAR)
    rows = re.findall(r"<text[^>]*>([^<]*)</text>", wide[0][1])
    assert len(rows) == 2 and all(len(r) <= per_row for r in rows) and rows[1].startswith(" " * 4)


@pytest.mark.parametrize("bad, words", [({"style": "code", "lines": [{"text": "print(1)"}]}, "needs `say`"),
                                        ({"style": "code", "lines": [{"text": "  ", "say": "x"}]}, "at least one line of code"),
                                        ({"style": "code", "lines": [{"text": "x = 1\n" * 6, "say": "x"}] * 9}, "at most")])
def test_code_mistakes_go_back_to_the_tutor(bad, words):
    with pytest.raises(SceneError, match=re.escape(words)):
        build_notes(bad, 1, [])


@needs_elk
def test_a_repeated_diagram_in_a_turn_goes_back_to_the_tutor(api, monkeypatch):
    client, _ = api
    nb_id = client.post("/api/notebooks", json={"topic": "Repeats"}).json()["id"]
    m, calls = _model([[("draw_scene", SCENE)], [("draw_scene", {**SCENE, "title": "Again"})]])
    with patch("engine.author.get_azure_client", lambda: m), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        assert client.post(f"/api/notebooks/{nb_id}/chat", json={"message": "Teach me"}).status_code == 200
    results = [msg["content"] for msg in calls[-1]["messages"] if isinstance(msg, dict) and msg.get("role") == "tool"]
    assert '"status": "ok"' in results[0] and "repeats block 1" in results[1]


def test_a_repeat_refusal_names_the_block_it_repeats():
    board = '<g id="b1_s1"><text>Sunlight holds every colour</text></g><g id="b7_s2"><text>Blue light scatters more than red light</text></g>'
    why = repeats("write_notes", {"lines": [{"text": "Blue light scatters much more than red"}]}, board)
    assert "(already in b7_s2)" in why                     # the tutor sees only the newest blocks' words; the id lets it point at older ones
